"""Hybrid pipeline: each problem's measured winner runs on every batch, and the LLM reviews only flagged rows
where the measurements say it improves on them. Winners come from results/b_detection.json, never hard-coded.

Usage: python -m project_b.pipeline
"""
from __future__ import annotations

import json
import time

import numpy as np

from common.config import RESULTS_DIR
from common.llm import CacheMiss, QuotaExhausted
from project_b import data, injector
from project_b.detectors import rules, stats
from project_b.detectors.base import BATCH_PROBLEMS, DetectionResult
from project_b.detectors.llm import LLMReview, ROWS_PER_CALL

BATCH_SIZE = 5000
MIXED_TRIALS = 3
CLEAN_TRIALS = 3
MIXED_RATE = 0.01
NULL_SPIKE_RATE = 0.05
TIE = 0.02
FAMILIES = {"rules": {c.problem: c for c in rules.ALL}, "stats": {c.problem: c for c in stats.ALL}}
# Duplicates reorder rows, so they go first with labels carried in temporary columns. Schema damage goes last.
ORDER = ["exact_duplicates", "near_duplicates", "lat_lon_swap", "closed_before_created", "zip_borough_mismatch", "complaint_descriptor_mismatch",
         "resolution_status_contradiction", "pii_in_text", "null_spike", "type_change", "date_format_switch", "renamed_dropped_column"]


def _score(cell: dict) -> tuple[float, float]:
    block = cell["by_rate"]["0.01"]
    detection = block["batch_detection"] if cell["batch_level"] else block["row_recall"]
    penalty = 10 * cell["clean_row_far"] + (0.5 * cell["clean_batch_alert_rate"] if cell["batch_level"] else 0)
    return detection - penalty, detection


def choose_winners(detection: dict) -> dict:
    """Best of rules and stats by detection minus a false-alarm penalty, with ties going to rules. LLM is an add-on, judged separately."""
    llm_cells = {c["problem"]: c for c in detection.get("llm_cells", [])}
    cells: dict = {}
    for cell in detection["cells"]:
        cells.setdefault(cell["problem"], {})[cell["family"]] = cell
    out = {}
    for problem, by_family in cells.items():
        rule_score, stat_score = _score(by_family["rules"])[0], _score(by_family["stats"])[0]
        family = "stats" if stat_score > rule_score + TIE else "rules"
        chosen = by_family[family]
        precision = chosen["by_rate"]["0.01"]["row_precision"]
        llm = llm_cells.get(problem) or {}
        llm_precision, llm_recall = llm.get("row_precision"), llm.get("row_recall_on_reviewed")
        better_precision = precision is not None and precision < 0.7 and (llm_precision or 0) >= 0.7 and (llm_recall or 0) >= 0.7
        out[problem] = {
            "primary": family,
            "score": round(_score(chosen)[0], 3),
            "detection": round(_score(chosen)[1], 3),
            "row_precision": precision,
            "llm_confirms_flags": bool(problem not in BATCH_PROBLEMS and better_precision),
            "llm_precision": llm_precision,
            "llm_recall": llm_recall,
        }
    return out


class HybridPipeline:
    def __init__(self, winners: dict):
        self.winners = winners

    def fit(self, reference):
        self.detectors = {p: FAMILIES[w["primary"]][p]().fit(reference) for p, w in self.winners.items()}
        self.reviewers = {p: LLMReview(p).fit(reference) for p, w in self.winners.items() if w["llm_confirms_flags"]}
        return self

    def run(self, batch, seed: int = 0) -> dict:
        out = {"flags": {}, "alerts": {}, "unreviewed": {}, "llm_calls": 0, "llm_cost_usd": 0.0, "llm_latency_s": 0.0, "llm_unavailable": 0}
        started = time.perf_counter()
        results: dict[str, DetectionResult] = {p: d.detect(batch) for p, d in self.detectors.items()}
        out["offline_seconds"] = time.perf_counter() - started
        for problem, result in results.items():
            flags, fired = result.row_flags.copy(), result.batch_alert
            review = self.reviewers.get(problem)
            candidates = np.flatnonzero(flags)
            if review is not None and len(candidates):
                rng = np.random.default_rng(seed)
                chosen = rng.choice(candidates, min(ROWS_PER_CALL, len(candidates)), replace=False)
                unreviewed = len(candidates) - len(chosen)
                try:
                    verdict = review.detect(batch, positions=chosen, sample_seed=seed)
                    out["llm_calls"] += 1
                    out["llm_cost_usd"] += verdict.cost_usd
                    out["llm_latency_s"] += verdict.latency_s
                    # Confirmed rows alert. Rows the LLM rejected are cleared. Rows over the review cap stay as low-confidence.
                    keep = verdict.row_flags.copy()
                    rest = np.setdiff1d(candidates, chosen)
                    out["unreviewed"][problem] = rest.tolist()
                    flags = keep
                    fired = bool(keep.any())
                    assert unreviewed == len(rest)
                except (QuotaExhausted, CacheMiss):
                    out["llm_unavailable"] += 1
            out["flags"][problem] = flags
            out["alerts"][problem] = bool(fired)
        return out


def mixed_batch(batch, reference, seed: int):
    """Inject all 12 problems into one batch and return it with labels aligned to the final row order."""
    frame = batch
    labels: dict[str, np.ndarray] = {}
    meta = {}
    for problem in ORDER:
        rate = NULL_SPIKE_RATE if problem == "null_spike" else MIXED_RATE
        injected = injector.inject(frame, problem, rate, seed=seed, reference=reference)
        frame = injected.batch
        meta[problem] = {k: v for k, v in injected.meta.items() if k in ("variant", "column", "new_name", "agency", "columns", "format")}
        if problem == "exact_duplicates":
            frame = frame.assign(__exact=injected.row_labels)
        elif problem == "near_duplicates":
            labels["exact_duplicates"] = frame["__exact"].fillna(False).to_numpy(dtype=bool)
            frame = frame.drop(columns="__exact")
            labels[problem] = injected.row_labels
        else:
            labels[problem] = injected.row_labels
    return frame, labels, meta


def evaluate() -> dict:
    detection = json.loads((RESULTS_DIR / "b_detection.json").read_text())
    winners = choose_winners(detection)
    reference, evaluation = data.splits()
    clean = data.clean_batches(evaluation, MIXED_TRIALS + CLEAN_TRIALS, BATCH_SIZE, seed=4242)
    pipeline = HybridPipeline(winners).fit(reference)

    per_problem = {p: {"tp": 0, "fn": 0, "fp": 0, "batch_hits": 0, "unreviewed": 0, "tp_unreviewed": 0} for p in winners}
    totals = {"llm_calls": 0, "llm_cost_usd": 0.0, "llm_latency_s": 0.0, "llm_unavailable": 0, "offline_seconds": 0.0, "rows": 0}
    metas = []
    for trial, batch in enumerate(clean[:MIXED_TRIALS]):
        frame, labels, meta = mixed_batch(batch, reference, seed=trial)
        metas.append(meta)
        result = pipeline.run(frame, seed=trial)
        for problem, record in per_problem.items():
            flags, truth = result["flags"][problem], labels[problem]
            record["tp"] += int((flags & truth).sum())
            record["fn"] += int((~flags & truth).sum())
            record["fp"] += int((flags & ~truth).sum())
            record["batch_hits"] += int(result["alerts"][problem])
            rest = result["unreviewed"].get(problem, [])
            record["unreviewed"] += len(rest)
            record["tp_unreviewed"] += int(truth[rest].sum()) if rest else 0
        for key in ("llm_calls", "llm_cost_usd", "llm_latency_s", "llm_unavailable", "offline_seconds"):
            totals[key] += result[key]
        totals["rows"] += len(frame)

    clean_alerts = {p: 0 for p in winners}
    clean_flags = {p: 0 for p in winners}
    clean_rows = 0
    for trial, batch in enumerate(clean[MIXED_TRIALS:]):
        result = pipeline.run(batch, seed=100 + trial)
        for problem in winners:
            clean_alerts[problem] += int(result["alerts"][problem])
            clean_flags[problem] += int(result["flags"][problem].sum())
        for key in ("llm_calls", "llm_cost_usd", "llm_latency_s", "llm_unavailable", "offline_seconds"):
            totals[key] += result[key]
        totals["rows"] += len(batch)
        clean_rows += len(batch)

    table = {}
    for problem, record in per_problem.items():
        positives = record["tp"] + record["fn"]
        table[problem] = {
            **record,
            "row_recall": round(record["tp"] / positives, 3) if positives else None,
            "row_recall_if_unreviewed_kept": round((record["tp"] + record["tp_unreviewed"]) / positives, 3) if positives else None,
            "row_precision": round(record["tp"] / (record["tp"] + record["fp"]), 3) if record["tp"] + record["fp"] else None,
            "batch_detected": f"{record['batch_hits']}/{MIXED_TRIALS}",
            "clean_batches_alerting": f"{clean_alerts[problem]}/{CLEAN_TRIALS}",
            "clean_row_far": round(clean_flags[problem] / clean_rows, 5),
        }
    cost_per_million = totals["llm_cost_usd"] / totals["rows"] * 1_000_000
    all_llm = [c["cost_per_million_usd"] for c in detection.get("llm_cells", []) if c.get("cost_per_million_usd") is not None]
    out = {
        "winners": winners,
        "mixed_trials": MIXED_TRIALS,
        "clean_trials": CLEAN_TRIALS,
        "per_problem": table,
        "injection_detail": metas,
        **totals,
        "offline_rows_per_s": round(totals["rows"] / max(totals["offline_seconds"], 1e-6)),
        "llm_cost_per_million_usd": round(cost_per_million, 2),
        "llm_calls_per_batch": round(totals["llm_calls"] / (MIXED_TRIALS + CLEAN_TRIALS), 2),
        "llm_only_cost_per_million_usd_all_12_checks": round(sum(all_llm), 2) if all_llm else None,
        "llm_only_cells_priced": len(all_llm),
        "coverage": data.coverage(),
    }
    (RESULTS_DIR / "b_pipeline.json").write_text(json.dumps(out, indent=1, default=lambda v: v.tolist() if hasattr(v, "tolist") else str(v)) + "\n")
    return out


if __name__ == "__main__":
    result = evaluate()
    for problem, record in result["per_problem"].items():
        print(f"{problem:33s} {result['winners'][problem]['primary']:5s} llm={result['winners'][problem]['llm_confirms_flags']!s:5s} recall={record['row_recall']} precision={record['row_precision']} batch={record['batch_detected']} clean={record['clean_batches_alerting']} far={record['clean_row_far']} unreviewed={record['unreviewed']}")
    print({k: result[k] for k in ("llm_calls", "llm_cost_per_million_usd", "llm_calls_per_batch", "llm_only_cost_per_million_usd_all_12_checks", "offline_rows_per_s", "llm_unavailable")})
