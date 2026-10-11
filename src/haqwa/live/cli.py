"""Commands for running or serving a faulted live shop."""

from __future__ import annotations

import asyncio
import os
import socket
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, cast
from zoneinfo import ZoneInfo

import typer
import uvicorn

from haqwa.core.compiler import compile_spec
from haqwa.core.errors import HaqwaError
from haqwa.core.report import format_text
from haqwa.core.spec import load_spec
from haqwa.demo.recording import RECORDINGS_DIR, save_effects

from .agent import DEFAULT_MODEL, TASKS, GeminiRequestCounter, run_adk_agent
from .report import DEFAULT_SPEC, verdict

if TYPE_CHECKING:
    from .server import LiveShop

Fault = Literal["timeout_after_commit", "stale_state"]

app = typer.Typer(help="Test an agent against a live MCP shop.")


def next_recording_path(fault: Fault, directory: Path = RECORDINGS_DIR) -> Path:
    """Choose the first free run number for this fault and local date."""
    day = datetime.now(ZoneInfo("Asia/Yangon")).strftime("%Y_%m_%d")
    label = "timeout" if fault == "timeout_after_commit" else "stale"
    number = 1
    while (path := directory / f"gemini_live_{label}_run_{number}_{day}.json").exists():
        number += 1
    return path


@asynccontextmanager
async def _running_server(shop: LiveShop):
    """Run one local MCP server on an OS-selected free port."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    config = uvicorn.Config(shop.mcp.streamable_http_app(), log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(100):
            if server.started:
                break
            if task.done():
                await task
            await asyncio.sleep(0.05)
        else:
            raise RuntimeError("MCP server did not start")
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        await task
        sock.close()


async def _run(fault: Fault, runs: int, model: str, spec: Path, record: bool) -> tuple[int, int]:
    from .server import build_server

    shop = build_server(fault)
    counter = GeminiRequestCounter()
    violations = 0
    async with _running_server(shop) as url:
        for number in range(1, runs + 1):
            shop.reset()
            typer.echo(f"Run {number}/{runs}")
            try:
                calls = await run_adk_agent(url, TASKS[fault], model, counter)
                for call in calls:
                    typer.echo(
                        f"Tool {call['name']} args={call['args']} result={call.get('result')}"
                    )
            except Exception as exc:
                typer.echo(f"Agent run failed: {type(exc).__name__}: {exc}", err=True)
                raise typer.Exit(4) from exc
            events, report = verdict(shop.effects(), spec)
            for event in events:
                typer.echo(f"Effect {event.event}: {event.data}")
            typer.echo(format_text(report))
            violations += not report.passed
            if record:
                path = next_recording_path(fault)
                save_effects(shop.effects(), path)
                typer.echo(f"Recorded effects: {path}")
    typer.echo(f"violation in {violations}/{runs} runs")
    typer.echo(f"Total Gemini requests: {counter.requests}")
    return violations, counter.requests


@app.command("run")
def run_command(
    fault: Annotated[str, typer.Option(help="Fault to inject.")],
    runs: Annotated[int, typer.Option()] = 1,
    model: Annotated[str, typer.Option()] = DEFAULT_MODEL,
    spec: Annotated[Path, typer.Option()] = DEFAULT_SPEC,
    record: Annotated[bool, typer.Option("--record/--no-record")] = True,
) -> None:
    """Run Gemini against the local shop and check its committed effects."""
    if fault not in TASKS or not 1 <= runs <= 5:
        typer.echo("Use a known --fault and --runs from 1 to 5.", err=True)
        raise typer.Exit(3)
    try:
        compile_spec(load_spec(spec))
    except (HaqwaError, OSError) as exc:
        typer.echo(f"Invalid spec: {exc}", err=True)
        raise typer.Exit(3) from exc
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        typer.echo("Set GEMINI_API_KEY or GOOGLE_API_KEY before a live run.", err=True)
        raise typer.Exit(4)
    try:
        violations, _ = asyncio.run(_run(cast(Fault, fault), runs, model, spec, record))
    except (HaqwaError, OSError) as exc:
        typer.echo(f"Invalid input: {exc}", err=True)
        raise typer.Exit(3) from exc
    raise typer.Exit(1 if violations else 0)


@app.command("serve")
def serve_command(
    fault: Annotated[str, typer.Option(help="Fault to inject.")],
    port: Annotated[int, typer.Option()] = 8765,
    spec: Annotated[Path, typer.Option()] = DEFAULT_SPEC,
) -> None:
    """Serve shop tools for an external MCP client; print the verdict on shutdown."""
    from .server import build_server

    if fault not in TASKS or not 1 <= port <= 65535:
        typer.echo("Use a known --fault and --port from 1 to 65535.", err=True)
        raise typer.Exit(3)
    try:
        compile_spec(load_spec(spec))
    except (HaqwaError, OSError) as exc:
        typer.echo(f"Invalid spec: {exc}", err=True)
        raise typer.Exit(3) from exc
    shop = build_server(cast(Fault, fault), port)
    typer.echo(f"Haqwa MCP shop: http://127.0.0.1:{port}/mcp")
    try:
        shop.mcp.run(transport="streamable-http")
    except KeyboardInterrupt:
        pass
    finally:
        try:
            events, report = verdict(shop.effects(), spec)
            for event in events:
                typer.echo(f"Effect {event.event}: {event.data}")
            typer.echo(format_text(report))
        except (HaqwaError, OSError) as exc:
            typer.echo(f"Cannot check effects: {exc}", err=True)
