"""Terminal demo: `python -m haqwa.demo [spec.yaml]` runs every scenario and prints reports."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from ..core.report import format_text
from ..core.spec import load_spec
from .scenarios import list_scenarios, run_scenario

DEFAULT_SPEC = Path("examples/shop/rules.spec.yaml")


def main(argv: list[str]) -> int:
    spec = load_spec(argv[0] if argv else DEFAULT_SPEC)
    ok = True
    for s in list_scenarios():
        start = time.perf_counter()
        events, report = run_scenario(s["id"], spec)
        ms = (time.perf_counter() - start) * 1000
        got = "pass" if report.passed else "violation"
        ok &= got == s["expected"]
        print(f"\n=== {s['title']}  [{s['fault']}]  ({ms:.0f} ms)")
        print(f"    {s['description']}")
        print(f"    effects: {[e.event for e in events]}")
        print(format_text(report))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
