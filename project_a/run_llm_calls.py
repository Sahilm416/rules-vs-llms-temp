"""Make the live query-time LLM calls and record them in llm_cache/. The evaluator only ever replays that cache.

Order matters because the free tier can run out: determinism repeats come first, then cases in a seeded
shuffle, so a partial run is still an unbiased sample. Safe to re-run; recorded calls are skipped.

Usage: python -m project_a.run_llm_calls {fy2024|fy2025|stale} [--model M] [--limit N] [--repeat-inputs K]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import random
from pathlib import Path

from common import llm
from common.llm import QuotaExhausted
from project_a.impl_llm_query import query

CASES_DIR = Path(__file__).parent / "tests" / "cases"
DETERMINISM_IDS = {
    "2024-25": [
        "2024-25-new_slab-700000_+0",
        "2024-25-rebate_new_breakeven--10",
        "2024-25-hra-odd_salary_metro",
        "2024-25-surcharge-old_50000000_+1000",
        "2024-25-stacked-1800000",
    ],
}
REPEATS = 10
STALE_SAMPLE = 40


def load_cases(fy: str) -> list[dict]:
    return json.loads((CASES_DIR / f"fy{fy.replace('-', '_')}.json").read_text())


def shuffled(cases: list[dict], seed: str) -> list[dict]:
    copy = list(cases)
    random.Random(seed).shuffle(copy)
    return copy


def plan(stage: str, repeat_inputs: int = 5) -> list[tuple[dict, int, str | None]]:
    if stage == "fy2024":
        cases = load_cases("2024-25")
        by_id = {c["id"]: c for c in cases}
        jobs = [(by_id[i]["input"], a, None) for i in DETERMINISM_IDS["2024-25"][:repeat_inputs] for a in range(REPEATS)]
        return jobs + [(c["input"], 0, None) for c in shuffled(cases, "query-2024-25")]
    if stage == "fy2025":
        return [(c["input"], 0, None) for c in shuffled(load_cases("2025-26"), "query-2025-26")]
    if stage == "stale":  # FY 2025-26 inputs answered from last year's rule text
        return [(c["input"], 0, "2024-25") for c in shuffled(load_cases("2025-26"), "stale")[:STALE_SAMPLE]]
    raise ValueError(stage)


def run(stage: str, model: str, limit: int | None, repeat_inputs: int, workers: int = 4) -> None:
    jobs = plan(stage, repeat_inputs)
    if limit is not None:
        jobs = jobs[:limit]
    done = errors = 0
    stop = False

    def one(job):
        inp, attempt, rules_fy = job
        return query.call(inp, attempt, rules_fy, model)

    with cf.ThreadPoolExecutor(workers) as pool:
        futures = [pool.submit(one, job) for job in jobs]
        for future in cf.as_completed(futures):
            try:
                future.result()
                done += 1
            except QuotaExhausted as exc:
                if not stop:
                    print(f"QUOTA {exc}", flush=True)
                stop = True
                for pending in futures:
                    pending.cancel()
            except cf.CancelledError:
                pass
            except Exception as exc:  # recorded as a gap by the evaluator
                errors += 1
                print(f"ERROR {exc}", flush=True)
            if done % 25 == 0 and done:
                print(f"progress {done}/{len(jobs)} errors={errors}", flush=True)
    print(f"FINISHED stage={stage} model={model} done={done}/{len(jobs)} errors={errors} quota_stop={stop}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["fy2024", "fy2025", "stale"])
    parser.add_argument("--model", default=query.MODEL)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--repeat-inputs", type=int, default=5)
    parser.add_argument("--interval", type=float, default=2.0, help="seconds between calls")
    args = parser.parse_args()
    llm.MIN_INTERVAL_S[args.model] = args.interval
    run(args.stage, args.model, args.limit, args.repeat_inputs)
