"""Command line entry points for creating, sealing and checking policies."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.text import Text

from .core.checker import check
from .core.compiler import compile_spec
from .core.errors import HaqwaError
from .core.events import load_event_map, load_events
from .core.report import format_text
from .core.spec import Spec, TimelineEvent, load_spec, save_spec, suggest_rule_id
from .core.trace import summarize_trace

app = typer.Typer(help="Build and check executable business policies.")
console = Console()

_SHOP_RULE = "A customer must not be charged twice for the same order.\n"
_SHOP_MAP = (
    "version: 1\nevents:\n  charged: PAYMENT_CAPTURED\n"
    "  refunded: REFUND_ISSUED\n  order_created: ORDER_CREATED\n"
)


def _fail(message: str, code: int) -> None:
    typer.echo(message, err=True)
    raise typer.Exit(code)


def _timeline_label(item: TimelineEvent) -> str:
    """Show every fact the owner is being asked to judge."""
    details = [
        f"{field}: {json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)}"
        for field, value in sorted(item.data.items())
    ]
    if item.at is not None:
        seconds = item.at.total_seconds()
        if seconds == 0:
            details.append("at the start")
        elif seconds % 3600 == 0:
            offset = f"{seconds / 3600:g} hours"
        else:
            offset = f"{seconds / 60:g} minutes" if seconds % 60 == 0 else f"{seconds:g} seconds"
        if seconds:
            details.append(f"at +{offset} from the first event")
    return item.event + (f" ({'; '.join(details)})" if details else "")


@app.command()
def init(directory: Annotated[Path, typer.Argument(metavar="[DIR]")] = Path(".")) -> None:
    """Create a starter rules file and event map without overwriting files."""
    files = {"rules.haqwa": _SHOP_RULE, "events.map.yaml": _SHOP_MAP}
    if directory.exists() and not directory.is_dir():
        _fail(f"Not a directory: {directory}", 3)
    existing = [directory / name for name in files if (directory / name).exists()]
    if existing:
        _fail(f"Refusing to overwrite: {', '.join(str(p) for p in existing)}", 3)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        for name, contents in files.items():
            (directory / name).write_text(contents, encoding="utf-8")
    except OSError as exc:
        _fail(f"Cannot initialize {directory}: {exc}", 3)
    typer.echo(f"Created {directory / 'rules.haqwa'} and {directory / 'events.map.yaml'}")


@app.command("check")
def check_command(
    spec: Annotated[Path, typer.Argument(metavar="SPEC")],
    events: Annotated[Path, typer.Argument(metavar="EVENTS")],
    event_map: Annotated[Path | None, typer.Option("--map", metavar="MAP")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Check JSON events against a sealed spec; no Gemini call is made."""
    try:
        sealed = load_spec(spec)
        mapping = load_event_map(event_map) if event_map else None
        compiled = compile_spec(sealed, mapping)
        report = check(compiled, load_events(events), mapping)
    except HaqwaError as exc:
        _fail(f"{exc.code}: {exc.detail}", exc.exit_code)
    except OSError as exc:
        _fail(f"Cannot read input file: {exc}", 3)
    if json_output:
        typer.echo(json.dumps(report.model_dump(mode="json"), ensure_ascii=False))
    else:
        typer.echo(format_text(report))
    raise typer.Exit(0 if report.passed else 1)


@app.command()
def inspect(
    events: Annotated[Path, typer.Argument(metavar="EVENTS")],
    event_map: Annotated[Path | None, typer.Option("--map", metavar="MAP")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show the vocabulary and structure of a C2 event trace."""
    try:
        loaded = load_events(events)
        if event_map is not None:
            loaded = load_event_map(event_map).translate(loaded)
        summary = summarize_trace(loaded)
    except HaqwaError as exc:
        _fail(f"{exc.code}: {exc.detail}", exc.exit_code)
    except OSError as exc:
        _fail(f"Cannot read input file: {exc}", 3)
    if json_output:
        typer.echo(summary.model_dump_json())
        return
    typer.echo(f"Events: {summary.event_count}")
    for name, count in summary.event_counts.items():
        typer.echo(f"  {name}: {count}")
    typer.echo(f"First: {summary.first_ts.isoformat() if summary.first_ts else 'none'}")
    typer.echo(f"Last: {summary.last_ts.isoformat() if summary.last_ts else 'none'}")
    typer.echo(f"Fields: {', '.join(summary.fields) or 'none'}")
    typer.echo("Closed values:")
    for field, values in summary.field_values.items():
        typer.echo(f"  {field}: {', '.join(values)}")
    typer.echo(f"Entity candidates: {', '.join(summary.entity_candidates) or 'none'}")


@app.command()
def build(
    rules: Annotated[Path, typer.Argument(metavar="RULES")],
    event_map: Annotated[Path | None, typer.Option("--map", metavar="MAP")] = None,
    output: Annotated[Path, typer.Option("-o", "--output")] = Path("rules.spec.yaml"),
    fields: Annotated[
        list[str] | None, typer.Option("--field", help="Event data field; repeat as needed.")
    ] = None,
    trace: Annotated[Path | None, typer.Option("--trace", metavar="EVENTS")] = None,
) -> None:
    """Ask the owner about each rule, self-test it, and save a sealed spec."""
    from .ai import (
        Answer,
        GeminiBadOutput,
        GeminiClient,
        GeminiQuotaError,
        GeminiUnavailable,
        ParseError,
        Vocabulary,
        apply_answers,
        clarify,
    )

    if trace is not None and fields:
        _fail("--trace and --field cannot be used together", 3)
    if trace is None and event_map is None:
        _fail("Provide --map or --trace", 3)
    try:
        mapping = load_event_map(event_map) if event_map else None
        lines = [s.strip() for s in rules.read_text(encoding="utf-8").splitlines()]
        if trace is not None:
            events = load_events(trace)
            events = mapping.translate(events) if mapping else events
            summary = summarize_trace(events, extra_events=mapping.vocabulary if mapping else ())
    except HaqwaError as exc:
        _fail(f"{exc.code}: {exc.detail}", exc.exit_code)
    except OSError as exc:
        _fail(f"Cannot read input file: {exc}", 3)
    lines = [s for s in lines if s and not s.startswith("#")]
    if not lines:
        _fail("No rules found", 3)
    if trace is not None:
        if not summary.vocabulary.events:
            _fail("Trace has no events in the rule vocabulary", 3)
        vocab = Vocabulary.model_validate(summary.vocabulary.model_dump())
    else:
        assert mapping is not None
        vocab = Vocabulary(events=sorted(mapping.vocabulary), fields=fields or ["order_id"])
    client = GeminiClient()
    accepted = []
    unsupported = []
    used_ids: set[str] = set()
    try:
        for line in lines:
            rule_id = suggest_rule_id(line, used_ids)
            outcome = clarify(line, rule_id=rule_id, vocab=vocab, client=client)
            if outcome.status == "unsupported":
                unsupported.append(f"{line}: {outcome.reason}")
                continue
            assert outcome.rule is not None
            answers = []
            for question in outcome.questions:
                console.print()
                console.print(Text(line, style="bold"))
                console.print(Text(question.text))
                for index, item in enumerate(question.timeline, 1):
                    console.print(Text(f"  {index}. {_timeline_label(item)}"))
                answers.append(Answer(question=question, allowed=typer.confirm("Allowed?")))
            result = apply_answers(outcome.rule, answers)
            if result.mismatches:
                for mismatch in result.mismatches:
                    typer.echo(f"Meaning mismatch: {mismatch}", err=True)
                replacement = typer.prompt(
                    "Rewrite the rule (leave blank to skip)", default=""
                ).strip()
                if replacement:
                    lines.append(replacement)
                continue
            accepted.append(result.rule)
            used_ids.add(result.rule.id)
    except (GeminiQuotaError, GeminiUnavailable) as exc:
        _fail(f"Gemini unavailable: {exc}", 4)
    except (GeminiBadOutput, ParseError) as exc:
        _fail(f"Could not interpret rule: {exc}", 2)
    for item in unsupported:
        typer.echo(f"Unsupported: {item}", err=True)
    if not accepted:
        _fail("No supported rules to save", 2)
    sealed = Spec(rules=accepted)
    try:
        compile_spec(sealed, mapping)
        save_spec(sealed, output)
    except HaqwaError as exc:
        _fail(f"{exc.code}: {exc.detail}", exc.exit_code)
    except OSError as exc:
        _fail(f"Cannot write spec: {exc}", 3)
    typer.echo(f"Saved {len(accepted)} rule(s) to {output}")


if __name__ == "__main__":
    app()
