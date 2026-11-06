"""Measure all three implementations for both years. LLM results replay llm_cache/ and never spend quota.

Writes results/a_comparison.json and results/a_stale.json. Every query-time model is reported separately
with its true sample size; missing calls are left out, never estimated.
"""
from __future__ import annotations

import json
import statistics
import time

from common.config import RESULTS_DIR
from common.llm import PRICES, _cache_path, cache_key, parse_json
from project_a.impl_compiled import compiler
from project_a.impl_llm_query import query
from project_a.impl_rules import engine
from project_a.run_llm_calls import DETERMINISM_IDS, REPEATS, load_cases, shuffled
from project_a.trace import check_answer

FYS = ("2024-25", "2025-26")
QUERY_MODELS = ("gemini-3.6-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite")
LOCAL_REPEATS = 10


def exact(answer: dict, expected: dict) -> bool:
    """Rupee-exact: tax payable under both regimes and the recommendation all match."""
    try:
        return (
            round(answer["old"]["tax_payable"]) == answer["old"]["tax_payable"] == expected["old"]["tax_payable"]
            and round(answer["new"]["tax_payable"]) == answer["new"]["tax_payable"] == expected["new"]["tax_payable"]
            and answer["recommended"] == expected["recommended"]
        )
    except (KeyError, TypeError):
        return False


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))]


def recorded(inp: dict, model: str, attempt: int = 0, rules_fy: str | None = None) -> dict | None:
    key = cache_key(model, query.build_prompt(inp, rules_fy), query.SYSTEM, query.SCHEMA, attempt)
    path = _cache_path(key)
    return json.loads(path.read_text()) if path.exists() else None


def _local(compute, cases: list[dict], fy: str) -> dict:
    wrong, traceable, latencies, errors = [], 0, [], 0
    for case in cases:
        started = time.perf_counter()
        try:
            answer = compute(case["input"])
        except Exception:
            errors += 1
            continue
        latencies.append((time.perf_counter() - started) * 1000)
        if not exact(answer, case["expected"]):
            wrong.append(case["id"])
        traceable += not check_answer(answer, fy)
    deterministic = all(
        len({json.dumps(compute(c["input"]), sort_keys=True) for _ in range(LOCAL_REPEATS)}) == 1 for c in cases[:: max(len(cases) // 20, 1)]
    )
    return {
        "n": len(cases),
        "exact": len(cases) - len(wrong) - errors,
        "errors": errors,
        "wrong_ids": wrong[:10],
        "traceable": traceable,
        "latency_ms_p50": percentile(latencies, 50),
        "latency_ms_p95": percentile(latencies, 95),
        "deterministic": deterministic,
        "repeat_inputs": len(cases[:: max(len(cases) // 20, 1)]),
        "cost_per_1000_usd": 0.0,
    }


def _query(model: str, cases: list[dict], fy: str) -> dict | None:
    rows = []
    for case in cases:
        rec = recorded(case["input"], model)
        if rec is None:
            continue
        rate_in, rate_out = PRICES[model]
        row = {
            "id": case["id"],
            "latency_s": rec["latency_s"],
            "cost": (rec["input_tokens"] * rate_in + rec["output_tokens"] * rate_out) / 1_000_000,
            "input_tokens": rec["input_tokens"],
            "output_tokens": rec["output_tokens"],
        }
        try:
            answer = parse_json(rec["text"])
            row["exact"] = exact(answer, case["expected"])
            row["silent_wrong"] = not row["exact"]
            row["traceable"] = not check_answer(answer, fy)
            row["got"] = (answer["old"]["tax_payable"], answer["new"]["tax_payable"])
        except (ValueError, KeyError, TypeError):
            row.update(exact=False, silent_wrong=False, traceable=False, invalid=True)
        row["expected"] = (case["expected"]["old"]["tax_payable"], case["expected"]["new"]["tax_payable"])
        rows.append(row)
    if not rows:
        return None
    return {
        "n": len(rows),
        "suite_size": len(cases),
        "exact": sum(r["exact"] for r in rows),
        "silent_wrong": sum(r["silent_wrong"] for r in rows),
        "invalid": sum(bool(r.get("invalid")) for r in rows),
        "traceable": sum(r["traceable"] for r in rows),
        "latency_s_p50": percentile([r["latency_s"] for r in rows], 50),
        "latency_s_p95": percentile([r["latency_s"] for r in rows], 95),
        "cost_per_1000_usd": 1000 * statistics.mean(r["cost"] for r in rows),
        "input_tokens_mean": statistics.mean(r["input_tokens"] for r in rows),
        "output_tokens_mean": statistics.mean(r["output_tokens"] for r in rows),
        "wrong_examples": [{"id": r["id"], "got": r.get("got"), "expected": r["expected"]} for r in rows if not r["exact"]][:8],
    }


def _determinism(model: str) -> list[dict]:
    """How many distinct answers came back from repeated calls on the same input."""
    by_id = {c["id"]: c for c in load_cases("2024-25")}
    out = []
    for case_id in DETERMINISM_IDS["2024-25"]:
        case = by_id[case_id]
        answers = []
        for attempt in range(REPEATS):
            rec = recorded(case["input"], model, attempt)
            if rec is None:
                continue
            try:
                answers.append(parse_json(rec["text"]))
            except ValueError:
                answers.append({"invalid": True})
        if len(answers) < 2:
            continue
        taxes = {(a.get("old", {}).get("tax_payable"), a.get("new", {}).get("tax_payable")) for a in answers}
        full = {json.dumps(a, sort_keys=True) for a in answers}
        out.append({
            "id": case_id,
            "repeats": len(answers),
            "distinct_tax_answers": len(taxes),
            "distinct_full_answers": len(full),
            "all_correct": all(exact(a, case["expected"]) for a in answers),
        })
    return out


def compare() -> dict:
    out: dict = {}
    for fy in FYS:
        cases = load_cases(fy)
        section = {"rules": _local(engine.compute, cases, fy)}
        for stage in ("raw", "reviewed"):
            try:
                module = compiler.load(stage, fy)
            except FileNotFoundError:
                continue
            section[f"compiled_{stage}"] = _local(module.compute, cases, fy)
        for model in QUERY_MODELS:
            result = _query(model, cases, fy)
            if result:
                section[f"query:{model}"] = result
        out[fy] = section
    out["determinism"] = {m: d for m in QUERY_MODELS if (d := _determinism(m))}
    return out


def stale() -> dict:
    """Task 5: what happens when FY 2025-26 requests run on last year's rules, with no error raised."""
    cases = load_cases("2025-26")

    def with_old_year(compute):
        def run(inp):
            return compute({**inp, "fy": "2024-25"})
        return run

    out = {}
    reviewed = compiler.load("reviewed", "2024-25")
    for name, compute in (("rules", engine.compute), ("compiled", reviewed.compute)):
        run = with_old_year(compute)
        wrong = [c for c in cases if not exact(run(c["input"]), c["expected"])]
        wrong_reco = [c for c in cases if run(c["input"])["recommended"] != c["expected"]["recommended"]]
        worst = max((abs(run(c["input"])["new"]["tax_payable"] - c["expected"]["new"]["tax_payable"]) for c in cases), default=0)
        out[name] = {"n": len(cases), "silently_wrong": len(wrong), "wrong_recommendation": len(wrong_reco), "worst_new_regime_error_rupees": worst}
    for name, compute in (("rules", engine.compute), ("compiled", reviewed.compute)):
        try:
            compute(cases[0]["input"]) if name == "compiled" else compute({**cases[0]["input"], "fy": "2026-27"})
            out[name]["loud_on_unknown_year"] = False
        except (ValueError, engine.UnsupportedYear):
            out[name]["loud_on_unknown_year"] = True

    stale_sample = shuffled(cases, "stale")
    for model in QUERY_MODELS:
        rows = []
        for case in stale_sample:
            rec = recorded(case["input"], model, rules_fy="2024-25")
            if rec is None:
                continue
            try:
                answer = parse_json(rec["text"])
            except ValueError:
                rows.append("invalid")
                continue
            rows.append("right" if exact(answer, case["expected"]) else "silent")
        if rows:
            out[f"query:{model}"] = {"n": len(rows), "silently_wrong": rows.count("silent"), "right_by_coincidence": rows.count("right"), "invalid": rows.count("invalid")}
    return out


def main() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "a_comparison.json").write_text(json.dumps(compare(), indent=1) + "\n")
    (RESULTS_DIR / "a_stale.json").write_text(json.dumps(stale(), indent=1) + "\n")


if __name__ == "__main__":
    main()
