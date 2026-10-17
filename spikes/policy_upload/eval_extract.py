"""Policy upload eval: extract rules from the golden policy as .md and as .docx.

Run from the repository root:
    uv run python spikes/policy_upload/eval_extract.py --dry-run
    uv run --env-file .env python spikes/policy_upload/eval_extract.py --fresh --label run1

Pass: every expected rule found in both files, no forbidden text, no unmatched rule.
Each live run costs 2 Gemini calls (one per file).
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import docx  # noqa: E402

from haqwa.ai.client import GeminiClient  # noqa: E402
from haqwa.ai.document import extract_text  # noqa: E402
from haqwa.ai.extract import extract_rules  # noqa: E402
from spikes.policy_upload.golden_extract import EXPECTED, FORBIDDEN  # noqa: E402

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
POLICY = HERE / "golden_policy.md"


def as_docx(markdown: str) -> bytes:
    """The same policy as a Word file: headings as paragraphs, one paragraph per line."""
    document = docx.Document()
    for line in markdown.splitlines():
        if line.strip():
            document.add_paragraph(line.lstrip("# "))
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def score(rules: list[dict[str, str]]) -> dict[str, Any]:
    """Match each extracted rule to at most one expected rule by key phrases."""
    found, unmatched, forbidden = set(), [], []
    for rule in rules:
        text = f"{rule['text']} {rule['quote']}".casefold()
        if any(word in text for word in FORBIDDEN):
            forbidden.append(rule["text"])
            continue
        hits = [rid for rid, words in EXPECTED.items() if all(w in text for w in words)]
        if hits:
            found.add(hits[0])
        else:
            unmatched.append(rule["text"])
    return {
        "found": sorted(found),
        "missing": sorted(set(EXPECTED) - found),
        "unmatched": unmatched,
        "forbidden": forbidden,
    }


class _DryRunSDK:
    """Answers with the golden sentences copied from the document (plumbing only)."""

    def __init__(self, document: str) -> None:
        self.models = self
        self.document = document

    def generate_content(self, **kwargs: Any) -> Any:
        lines = [ln for ln in self.document.splitlines() if re.search(r"\bmust\b|\bneed\b", ln)]
        lines = [ln for ln in lines if "expected to" not in ln]
        answer = {"rules": [{"rule": ln, "quote": ln} for ln in lines]}

        class Response:
            text = json.dumps(answer)

        return Response()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="fake Gemini, no quota")
    parser.add_argument("--fresh", action="store_true", help="bypass the application cache")
    parser.add_argument("--label", help="save runs/extract_<label>.json")
    args = parser.parse_args(argv)
    markdown = POLICY.read_text(encoding="utf-8")
    files = {"golden_policy.md": markdown.encode(), "golden_policy.docx": as_docx(markdown)}
    rows = []
    for name, data in files.items():
        document = extract_text(name, data)
        sdk = _DryRunSDK(document.text) if args.dry_run else None
        client = GeminiClient(
            model="dry-run" if sdk else None,
            sdk=sdk,
            cache_dir=None if args.fresh or sdk else Path(".haqwa_cache"),
        )
        outcome = extract_rules(document.text, client=client)
        rules = [r.model_dump() for r in outcome.rules]
        rows.append(
            {
                "file": name,
                "chars": len(document.text),
                "cached": outcome.cached,
                "rules": rules,
                "dropped": [d.model_dump() for d in outcome.dropped],
                **score(rules),
            }
        )
    passed = all(not r["missing"] and not r["unmatched"] and not r["forbidden"] for r in rows)
    report = {"eval": "policy-extract", "dry_run": args.dry_run, "passed": passed, "files": rows}
    text = json.dumps(report, indent=2, ensure_ascii=False)
    print(text)
    if args.label:
        RUNS.mkdir(exist_ok=True)
        (RUNS / f"extract_{args.label}.json").write_text(text + "\n", encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
