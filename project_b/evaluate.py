"""Measure every detector family on every problem. Writes results/b_detection.json.

Rules and statistics: `TRIALS` batches at each rate, whole batch scanned.
LLM: a small measured sample (free-tier quota), with Wilson intervals. Row-level LLM review uses an enriched list of
rows so that recall can be measured at all. The deployed recall of random sampling is that recall times the coverage,
which is reported separately and never hidden. Nothing is extrapolated beyond the stated n.

The recorded LLM sample is pinned: it ran on a 286-day split while the download was in progress, and the coverage is
stored with it. Batches depend on the split, so re-running on other data would be new paid calls, not a replay, and
`llm` refuses unless given --force. `merge` keeps the recorded sample and its coverage label.

Usage: python -m project_b.evaluate {offline|llm [--force]|merge}
"""
from __future__ import annotations

import json
import math
import sys
import time

import numpy as np

from common.config import RESULTS_DIR
from common.llm import CacheMiss, QuotaExhausted
from project_b import data, injector
from project_b.detectors import rules, stats
from project_b.detectors.base import BATCH_PROBLEMS, text, number
from project_b.detectors.llm import LLMReview, ROWS_PER_CALL

BATCH_SIZE = 5000
TRIALS = 5
CLEAN_BATCHES = 5
RATES = (0.01, 0.05)
LLM_RATE = 0.05
LLM_CORRUPTED_CALLS = 2
LLM_CLEAN_CALLS = 1
RUBRIC = "One point each: names specific rows; names columns; states the observed value; states the expected value; gives a readable reason of 20+ characters. Mean over alerts, 0-5. Batch-level alerts about a whole column cannot name rows and lose that point unless they flag rows."


def wilson(hits: int, n: int, z: float = 1.96) -> list:
    if n == 0:
        return [None, None]
    p = hits / n
    denom = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, mid - half), 3), round(min(1.0, mid + half), 3)]


def explain_score(alerts: list) -> float | None:
    if not alerts:
        return None
    return round(float(np.mean([sum((bool(a.rows), bool(a.columns), bool(str(a.observed).strip()), bool(str(a.expected).strip()), len(str(a.reason)) >= 20)) for a in alerts])), 2)


def setup():
    reference, evaluation = data.splits()
    clean = data.clean_batches(evaluation, TRIALS + CLEAN_BATCHES, BATCH_SIZE, seed=2023)
    return reference, clean[:TRIALS], clean[TRIALS:]


def measure_offline(detector, reference, batches, clean) -> dict:
    problem = detector.problem
    out = {"family": detector.family, "problem": problem, "by_rate": {}, "batch_level": problem in injector.BATCH_LEVEL}
    alerts = []
    for rate in RATES:
        row_hits = row_total = fp = negatives = fired = 0
        for trial, batch in enumerate(batches):
            injected = injector.inject(batch, problem, rate, seed=trial, reference=reference)
            result = detector.detect(injected.batch)
            labels = injected.row_labels
            row_hits += int((result.row_flags & labels).sum())
            row_total += int(labels.sum())
            fp += int((result.row_flags & ~labels).sum())
            negatives += int((~labels).sum())
            fired += int(result.batch_alert)
            alerts += result.alerts
        flagged = row_hits + fp
        out["by_rate"][str(rate)] = {
            "row_recall": round(row_hits / max(row_total, 1), 4),
            "row_precision": round(row_hits / flagged, 4) if flagged else None,
            "batch_detection": round(fired / len(batches), 3),
            "corrupted_rows": row_total,
            "trials": len(batches),
        }
    started = time.perf_counter()
    clean_results = [detector.detect(b) for b in clean]
    seconds = time.perf_counter() - started
    rows = sum(len(b) for b in clean)
    out["clean_row_far"] = round(sum(int(r.row_flags.sum()) for r in clean_results) / rows, 5)
    out["clean_batch_alert_rate"] = round(sum(r.batch_alert for r in clean_results) / len(clean), 3)
    out["clean_batches"] = len(clean)
    out["throughput_rows_per_s"] = round(rows / max(seconds, 1e-6))
    out["cost_per_million_usd"] = 0.0
    out["explainability"] = explain_score(alerts)
    example = alerts[0] if alerts else None
    out["example_alert"] = None if example is None else {"columns": example.columns[:5], "observed": str(example.observed)[:200], "expected": str(example.expected)[:200], "reason": str(example.reason)[:200]}
    return out


def primary_detection(cell: dict, rate: str = "0.01") -> float:
    block = cell["by_rate"][rate]
    return block["batch_detection"] if cell["batch_level"] else block["row_recall"]


def run_offline() -> dict:
    reference, batches, clean = setup()
    cells = []
    for cls in (*rules.ALL, *stats.ALL):
        started = time.perf_counter()
        detector = cls().fit(reference)
        fit_s = time.perf_counter() - started
        cell = measure_offline(detector, reference, batches, clean)
        cell["fit_seconds"] = round(fit_s, 1)
        cells.append(cell)
        print(f"{cell['family']:6s} {cell['problem']:33s} det@1%={primary_detection(cell):.3f} det@5%={primary_detection(cell, '0.05'):.3f} far={cell['clean_row_far']:.5f} clean_alerts={cell['clean_batch_alert_rate']:.2f} {cell['throughput_rows_per_s']} r/s fit={fit_s:.0f}s", flush=True)
    out = {"batch_size": BATCH_SIZE, "trials": TRIALS, "rates": RATES, "coverage": data.coverage(), "rubric": RUBRIC, "cells": cells}
    (RESULTS_DIR / "b_detection_offline.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


def review_positions(batch, labels, problem: str, seed: int) -> np.ndarray:
    """An enriched review list: up to 10 corrupted rows, the rows they duplicate, and random rows to fill it."""
    rng = np.random.default_rng(seed)
    corrupted = np.flatnonzero(labels)
    chosen = list(rng.choice(corrupted, min(10, len(corrupted)), replace=False)) if len(corrupted) else []
    if problem in ("exact_duplicates", "near_duplicates"):
        lat, lon, kinds = number(batch, "latitude").to_numpy(), number(batch, "longitude").to_numpy(), text(batch, "complaint_type").to_numpy()
        for row in list(chosen):
            partners = np.flatnonzero((lat == lat[row]) & (lon == lon[row]) & (kinds == kinds[row]) & ~labels)
            chosen += list(partners[:1])
    pool = np.setdiff1d(np.arange(len(batch)), np.array(chosen, dtype=int))
    fill = rng.choice(pool, max(ROWS_PER_CALL - len(chosen), 0), replace=False)
    return np.sort(np.concatenate([np.array(chosen, dtype=int), fill]))


def run_llm(force: bool = False) -> dict:
    recorded = RESULTS_DIR / "b_detection_llm.json"
    if recorded.exists() and not force:
        existing = json.loads(recorded.read_text())
        current = data.coverage()["days"]
        pinned = (existing.get("coverage") or {}).get("days")
        if pinned != current:
            print(f"LLM sample is pinned to {pinned} days and data has {current}: keeping it. Use --force to spend new quota.", flush=True)
            return existing
    reference, batches, clean = setup()
    calls = {"gemini-3.5-flash-lite": 0, "gemini-3.1-flash-lite": 0}
    state = {p: {"family": "llm", "problem": p, "calls": [], "alerts": []} for p in injector.PROBLEMS}
    detectors = {p: LLMReview(p).fit(reference) for p in injector.PROBLEMS}
    plan = [(p, "corrupted", t) for t in range(LLM_CORRUPTED_CALLS) for p in injector.PROBLEMS] + [(p, "clean", t) for t in range(LLM_CLEAN_CALLS) for p in injector.PROBLEMS]
    exhausted = False
    for problem, kind, trial in plan:
        detector = detectors[problem]
        if kind == "corrupted":
            injected = injector.inject(batches[trial], problem, LLM_RATE, seed=trial, reference=reference)
            batch, labels = injected.batch, injected.row_labels
        else:
            batch, labels = clean[trial], np.zeros(len(clean[trial]), dtype=bool)
        positions = None if problem in BATCH_PROBLEMS else review_positions(batch, labels, problem, 100 + trial)
        try:
            result = detector.detect(batch, positions=positions, sample_seed=trial)
        except (QuotaExhausted, CacheMiss) as exc:
            print(f"STOP {type(exc).__name__}: {str(exc)[:120]}", flush=True)
            exhausted = True
            break
        calls[result.model] = calls.get(result.model, 0) + 1
        reviewed = np.zeros(len(batch), dtype=bool)
        if positions is not None:
            reviewed[positions] = True
        state[problem]["calls"].append({
            "kind": kind, "model": result.model, "fired": bool(result.batch_alert), "cost": result.cost_usd, "latency_s": result.latency_s,
            "input_tokens": result.input_tokens, "output_tokens": result.output_tokens, "reviewed_rows": result.reviewed_rows,
            "tp": int((result.row_flags & labels).sum()), "fn": int((reviewed & labels & ~result.row_flags).sum()),
            "fp": int((result.row_flags & ~labels).sum()), "tn": int((reviewed & ~labels & ~result.row_flags).sum()),
        })
        state[problem]["alerts"] += result.alerts
        print(f"{problem:33s} {kind:9s} {result.model} fired={result.batch_alert} tp={state[problem]['calls'][-1]['tp']} fp={state[problem]['calls'][-1]['fp']} {result.latency_s:.1f}s", flush=True)
    cells = []
    for problem, block in state.items():
        records = block["calls"]
        corrupted = [c for c in records if c["kind"] == "corrupted"]
        cleaned = [c for c in records if c["kind"] == "clean"]
        batch_problem = problem in BATCH_PROBLEMS
        tp, fn = sum(c["tp"] for c in corrupted), sum(c["fn"] for c in corrupted)
        fp, tn = sum(c["fp"] for c in records), sum(c["tn"] for c in records)
        hits = sum(c["fired"] for c in corrupted)
        cost_call = float(np.mean([c["cost"] for c in records])) if records else None
        reviewed = float(np.mean([c["reviewed_rows"] for c in records])) if records else None
        latency = float(np.mean([c["latency_s"] for c in records])) if records else None
        per_million = None
        if cost_call is not None:
            per_million = cost_call * (1_000_000 / BATCH_SIZE) if batch_problem else cost_call / reviewed * 1_000_000
        cells.append({
            "family": "llm", "problem": problem, "mode": "batch profile + sample" if batch_problem else "row review, enriched list",
            "n_calls": len(records), "n_corrupted_calls": len(corrupted), "n_clean_calls": len(cleaned),
            "models": sorted({c["model"] for c in records}),
            "batch_detection": round(hits / len(corrupted), 3) if corrupted else None,
            "batch_detection_ci": wilson(hits, len(corrupted)),
            "row_recall_on_reviewed": round(tp / (tp + fn), 3) if tp + fn else None,
            "row_recall_ci": wilson(tp, tp + fn), "corrupted_rows_reviewed": tp + fn,
            "row_fp_rate_on_reviewed": round(fp / (fp + tn), 4) if fp + tn else None,
            "row_fp_ci": wilson(fp, fp + tn), "clean_rows_reviewed": fp + tn,
            "row_precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "clean_alert_rate": round(sum(c["fired"] for c in cleaned) / len(cleaned), 3) if cleaned else None,
            "random_sample_coverage": None if batch_problem else round(ROWS_PER_CALL / BATCH_SIZE, 4),
            "deployed_recall_one_call_per_batch": None if batch_problem or not tp + fn else round(tp / (tp + fn) * ROWS_PER_CALL / BATCH_SIZE, 4),
            "cost_per_million_usd": None if per_million is None else round(per_million, 2),
            "cost_basis": "one call per 5,000-row batch" if batch_problem else "every row reviewed, 40 rows per call",
            "mean_latency_s": None if latency is None else round(latency, 2),
            "throughput_rows_per_s": None if latency is None else round(reviewed / latency, 1),
            "explainability": explain_score(block["alerts"]),
        })
    out = {"rate": LLM_RATE, "coverage": data.coverage(), "calls_by_model": calls, "quota_stopped": exhausted, "cells": cells}
    (RESULTS_DIR / "b_detection_llm.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(calls), "quota_stopped", exhausted, flush=True)
    return out


def merge() -> dict:
    offline = json.loads((RESULTS_DIR / "b_detection_offline.json").read_text())
    llm_path = RESULTS_DIR / "b_detection_llm.json"
    llm = json.loads(llm_path.read_text()) if llm_path.exists() else {"cells": [], "calls_by_model": {}, "quota_stopped": None}
    merged = {**offline, "llm_rate": llm.get("rate"), "llm_calls_by_model": llm["calls_by_model"], "llm_quota_stopped": llm["quota_stopped"], "llm_coverage": llm.get("coverage"), "llm_cells": llm["cells"]}
    (RESULTS_DIR / "b_detection.json").write_text(json.dumps(merged, indent=1) + "\n")
    return merged


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "merge"
    if stage == "llm":
        run_llm(force="--force" in sys.argv)
    else:
        {"offline": run_offline, "merge": merge}[stage]()
