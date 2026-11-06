"""One command that reproduces every reported number: python run_all.py

LLM results replay from llm_cache/, so no API key or quota is needed. Data downloads on the first run.
Each step runs in its own process; the run continues past a failure and exits non-zero if any step failed.
"""
from __future__ import annotations

import subprocess
import sys
import time

STEPS = [
    ("Unit tests and frozen test suites", ["-m", "pytest", "project_a", "project_b", "-q"]),
    ("Download NYC 311 2023 (skips finished days)", ["-m", "project_b.download"]),
    ("Project A: evaluate parsers", ["-m", "project_a.evaluate_parser"]),
    ("Project A: evaluate implementations", ["-m", "project_a.evaluate"]),
    ("Project A: official calculator checks", ["-m", "project_a.check_official"]),
    ("Project A: build RESULTS_A.md", ["-m", "project_a.report"]),
    ("Project B: profile raw data", ["-m", "project_b.profile_raw"]),
    ("Project B: evaluate rule and statistical detectors", ["-m", "project_b.evaluate", "offline"]),
    ("Project B: merge with recorded LLM results", ["-m", "project_b.evaluate", "merge"]),
    ("Project B: hybrid pipeline", ["-m", "project_b.pipeline"]),
    ("Project B: scale projection", ["-m", "project_b.scale"]),
]


def main() -> int:
    failed = []
    for name, args in STEPS:
        print(f"\n=== {name} ===", flush=True)
        started = time.perf_counter()
        code = subprocess.call([sys.executable, *args])
        print(f"--- {'ok' if code == 0 else f'FAILED ({code})'} in {time.perf_counter() - started:.1f}s", flush=True)
        if code:
            failed.append(name)
    print("\nAll steps passed." if not failed else f"\nFailed steps: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
