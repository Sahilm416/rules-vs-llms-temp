"""Project the measured pipeline to 50M rows a day across 120 customers, then write RESULTS_B.md.

Every input comes from results/b_detection.json, b_pipeline.json and b_profile.json. Stated assumptions are named
in the output. Compute is reported in cores, not dollars, because no compute price was measured.

Usage: python -m project_b.scale
"""
from __future__ import annotations

import json
import math

from common.config import RESULTS_DIR, ROOT

ROWS_PER_DAY = 50_000_000
CUSTOMERS = 120
BATCH_SIZE = 5000
PEAK_FACTOR = 3  # assumption: not measured


def load(name: str):
    path = RESULTS_DIR / name
    return json.loads(path.read_text()) if path.exists() else None


def project(detection: dict, pipeline: dict) -> dict:
    batches = ROWS_PER_DAY / BATCH_SIZE
    rows_per_s = pipeline["offline_rows_per_s"]
    average_rows_per_s = ROWS_PER_DAY / 86400
    llm_calls_day = pipeline["llm_calls_per_batch"] * batches
    schema_cell = next((c for c in detection.get("llm_cells", []) if c["problem"] == "renamed_dropped_column" and c.get("cost_per_million_usd") is not None), None)
    schema_call_cost = schema_cell["cost_per_million_usd"] * BATCH_SIZE / 1_000_000 if schema_cell else None
    llm_only = pipeline.get("llm_only_cost_per_million_usd_all_12_checks")
    hybrid_day = pipeline["llm_cost_per_million_usd"] * ROWS_PER_DAY / 1_000_000
    return {
        "rows_per_day": ROWS_PER_DAY,
        "customers": CUSTOMERS,
        "rows_per_customer_day_if_even": round(ROWS_PER_DAY / CUSTOMERS),
        "batches_per_day": round(batches),
        "average_rows_per_s": round(average_rows_per_s),
        "measured_one_core_rows_per_s": rows_per_s,
        "cores_average": round(average_rows_per_s / rows_per_s, 2),
        "cores_at_peak_assumption": max(1, math.ceil(PEAK_FACTOR * average_rows_per_s / rows_per_s)),
        "core_hours_per_day": round(ROWS_PER_DAY / rows_per_s / 3600, 1),
        "seconds_per_batch_offline": round(BATCH_SIZE / rows_per_s, 2),
        "llm_calls_per_day": round(llm_calls_day),
        "llm_requests_per_minute_average": round(llm_calls_day / 1440, 1),
        "hybrid_llm_usd_per_day": round(hybrid_day, 2),
        "hybrid_llm_usd_per_year": round(hybrid_day * 365),
        "llm_only_usd_per_day": None if llm_only is None else round(llm_only * ROWS_PER_DAY / 1_000_000, 2),
        "llm_only_cells_priced": pipeline.get("llm_only_cells_priced"),
        "schema_mapping_one_time_usd_estimate": None if schema_call_cost is None else round(schema_call_cost * CUSTOMERS, 2),
        "peak_factor_assumption": PEAK_FACTOR,
    }


def fmt(value, digits=3):
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}".rstrip("0").rstrip(".") if value else "0"
    return str(value)


def pct(value, digits=1):
    return "n/a" if value is None else f"{100 * value:.{digits}f}%"


def detection_table(detection: dict) -> str:
    llm = {c["problem"]: c for c in detection.get("llm_cells", [])}
    lines = [
        "| Problem | Family | Detection at 1% | Detection at 5% | Row precision at 1% | Clean row false alarms | Clean batches alerting | $ per 1M rows | Rows/s | Alert clarity (0-5) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    by_problem: dict = {}
    for cell in detection["cells"]:
        by_problem.setdefault(cell["problem"], []).append(cell)
    for problem, cells in by_problem.items():
        for cell in cells:
            low, high = cell["by_rate"]["0.01"], cell["by_rate"]["0.05"]
            batch = cell["batch_level"]
            d1 = low["batch_detection"] if batch else low["row_recall"]
            d5 = high["batch_detection"] if batch else high["row_recall"]
            lines.append(f"| {problem} | {cell['family']} | {pct(d1)} | {pct(d5)} | {pct(low['row_precision'])} | {pct(cell['clean_row_far'], 2)} | {pct(cell['clean_batch_alert_rate'], 0)} | $0 API | {cell['throughput_rows_per_s']:,} | {fmt(cell['explainability'], 2)} |")
        c = llm.get(problem)
        if c and c["n_calls"]:
            if c["batch_detection"] is not None and c["row_recall_on_reviewed"] is None:
                detected = f"{pct(c['batch_detection'], 0)} of {c['n_corrupted_calls']} batches, CI {c['batch_detection_ci']}"
            else:
                detected = f"{pct(c['row_recall_on_reviewed'], 0)} of {c['corrupted_rows_reviewed']} reviewed rows, CI {c['row_recall_ci']}"
            far = f"{pct(c['row_fp_rate_on_reviewed'], 1)} of {c['clean_rows_reviewed']} reviewed" if c["clean_rows_reviewed"] else "row rate n/a"
            lines.append(f"| {problem} | llm | {detected} | not run | {pct(c['row_precision'])} | {far} | {fmt(c['clean_alert_rate'])} of {c['n_clean_calls']} clean calls fired | ${fmt(c['cost_per_million_usd'], 2)} | {fmt(c['throughput_rows_per_s'], 1)} | {fmt(c['explainability'], 2)} |")
        else:
            lines.append(f"| {problem} | llm | not measured: quota | - | - | - | - | - | - | - |")
    return "\n".join(lines)


def pipeline_table(pipeline: dict) -> str:
    lines = ["| Problem | Primary check | LLM confirms flags | Row recall | Recall if unreviewed rows are kept | Row precision | Batch alert | Clean batches alerting | Clean row false alarms | Left unreviewed |", "|---|---|---|---|---|---|---|---|---|---|"]
    for problem, row in pipeline["per_problem"].items():
        winner = pipeline["winners"][problem]
        lines.append(f"| {problem} | {winner['primary']} | {'yes' if winner['llm_confirms_flags'] else 'no'} | {pct(row['row_recall'])} | {pct(row['row_recall_if_unreviewed_kept'])} | {pct(row['row_precision'])} | {row['batch_detected']} | {row['clean_batches_alerting']} | {pct(row['clean_row_far'], 2)} | {row['unreviewed']} |")
    return "\n".join(lines)


def issues_table(profile: dict) -> str:
    lines = ["| Issue | Rows | Share | Example |", "|---|---|---|---|"]
    for name, item in profile["findings"].items():
        if item.get("count") is None:
            continue
        example = (item.get("examples") or [{}])[0]
        lines.append(f"| {name.replace('_', ' ')} | {item['count']:,} | {item.get('pct', 0)}% | {json.dumps(example, ensure_ascii=False)[:150].replace('|', '/')} |")
    return "\n".join(lines)


def report(detection: dict, pipeline: dict, profile: dict, scale: dict) -> str:
    coverage = detection["coverage"]
    llm_cov = detection["llm_coverage"]
    partial = coverage.get("partial_2023")
    pii = profile["pii_triage"]
    repeated = pii["phone"]["rows_on_repeated_contacts"]
    llm_calls = detection.get("llm_calls_by_model", {})
    confirming = [p for p, w in pipeline["winners"].items() if w["llm_confirms_flags"]]
    schema_hits = "; ".join(f"{m['renamed_dropped_column'].get('column')} ({m['renamed_dropped_column'].get('variant')})" for m in pipeline["injection_detail"])
    missing = [c["problem"] for c in detection.get("llm_cells", []) if not c["n_calls"]]
    stopped = detection.get("llm_quota_stopped")
    return f"""# Project B results: data-quality checks

Reproduce the evaluation with `python -m project_b.evaluate offline && python -m project_b.evaluate merge && python -m project_b.pipeline && python -m project_b.scale`.

## Read this first

- **Data coverage:** rules, statistics, the hybrid pipeline and the profile use {coverage['days']} days ({coverage['first_day']} to {coverage['last_day']}). {'**This is a partial year.** ' if partial else ''}
- **LLM rows are from a partial year:** the LLM sample ran on {llm_cov['days']} days ({llm_cov['first_day']} to {llm_cov['last_day']}) while the download was in progress, and was kept to save quota. It was not re-run, so **LLM rows and the other rows do not come from the same batches**. The split was confirmed by matching a rebuilt prompt to the recorded call. Treat LLM against rules or statistics as indicative, not a head-to-head.
- **LLM sample is small:** {json.dumps(llm_calls)} calls{', stopped early by quota' if stopped else ''}. Intervals are 95% Wilson. {('Not measured: ' + ', '.join(missing) + '.') if missing else ''} LLM cells were measured at a 5% injection rate on an enriched review list, so their recall is not comparable to a full-batch scan. One call per batch reviews only 0.8% of a 5,000-row batch.
- **Self-authored test:** the same AI session wrote the injector and detectors, and the near-duplicate rule and the descriptor allow-list threshold were changed after the injector was visible. The rule keyword lists predate it. Treat rule recall as an upper bound.
- **Clean batches are scrubbed:** rows with known real problems were removed first. Thresholds were fitted on the earlier period, but the null-spike column exclusions and PII allow-list were added after looking at clean-batch false alarms, so those false-alarm rates are slightly optimistic.
- **Cost:** LLM dollars are real token counts at list price; the calls were free-tier. Rules and statistics show $0 API, and their compute is not priced.
- **Clarity score:** {detection['rubric']}

## Per-problem detection, false alarms and cost

`llm` rows: {llm_cov['days']}-day split, 5% injection, enriched review list, {detection['llm_cells'][0]['n_clean_calls']} clean call per problem. All other rows: {coverage['days']}-day split, whole batches, {detection['trials']} trials.

{detection_table(detection)}

Batch-level problems report the share of corrupted batches detected; others report row recall. "Clean batches alerting" counts any flagged row, so one false row in 5,000 counts as an alerting batch.

## Hybrid pipeline, end to end

All 12 problems injected at once in {pipeline['mixed_trials']} batches, plus {pipeline['clean_trials']} clean batches, on the {pipeline['coverage']['days']}-day split. Rates are 1%, except null spike at 5%. The decision to use the LLM rests on the {llm_cov['days']}-day sample above, while its calls in this run were made on the {pipeline['coverage']['days']}-day batches.

{pipeline_table(pipeline)}

- LLM confirms flags on: {', '.join(confirming) if confirming else 'nothing: on these measurements no LLM cell met the precision and recall bar'}.
- LLM calls: {pipeline['llm_calls']} ({pipeline['llm_calls_per_batch']} per batch), {pipeline['llm_unavailable']} unavailable because of quota. LLM cost: **${pipeline['llm_cost_per_million_usd']} per million rows**.
- Offline stages: {pipeline['offline_rows_per_s']:,} rows/s on one laptop process.
- Reviewing every row for every LLM-priced check would cost about ${fmt(pipeline['llm_only_cost_per_million_usd_all_12_checks'], 2)} per million rows ({pipeline['llm_only_cells_priced']} checks priced).
- **The review cap costs recall.** Only 40 flagged rows per check are reviewed in each batch, and the rest raise no alert, so near-duplicate recall collapses when candidates far exceed the cap. Real repeat callers cause that excess. The "Recall if unreviewed rows are kept" column shows the recall if those rows stay as low-confidence flags. Reviewing all of them would take more calls per batch than the cost above, and was not measured.
- **Schema damage silences other checks.** The column hit in each mixed batch was: {schema_hits}. Any check needing that column finds nothing in that batch, which lowers recall for ZIP, resolution and PII. The schema alert did fire in every mixed batch. Quarantining a batch on that alert is the recommended behaviour, but it isn't implemented here.
- **Later injections alter earlier ones.** An exact copy changed by a later problem is no longer exact, which lowers duplicate recall in this mixed test.

## Real issues in the raw data

{issues_table(profile)}

Other findings:

- **Duplicates:** {profile['duplicates']['duplicate_unique_key']:,} repeated unique keys, and {profile['duplicates']['same_content_different_key']:,} rows with the same content under a different key.
- **Published contacts look like personal data:** {pii['phone']['rows_with_match']:,} rows match a phone pattern, but {repeated:,} are on repeated agency service lines. Only {pii['phone']['rows_on_rare_contacts']} phone rows and {pii['email']['rows_on_rare_contacts']} email rows are candidates for manual review, and none is confirmed as personal data.
- **Placeholders and casing:** `descriptor` holds the literal `N/A` on {profile['placeholder_values']['descriptor']['count']:,} rows, and `complaint_type` has {profile['casing_variants']['complaint_type']['groups']} groups of case variants across {profile['casing_variants']['complaint_type']['rows']:,} rows.
- **Lifecycle nulls:** during development on a partial split, DHS `closed_date` was 51-90% null in clean evaluation batches against a 14% baseline. It depends on request age, so lifecycle columns are excluded from null-spike checks instead of being raised as alarms.

## Scale design: 50M rows a day, 120 customers

Assumes rows arrive evenly ({scale['rows_per_customer_day_if_even']:,} per customer per day), in 5,000-row batches, at a {scale['peak_factor_assumption']}x peak (not measured). This 44-column public dataset stands in for customer data.

| Measure | Projection |
|---|---|
| Batches per day | {scale['batches_per_day']:,} |
| Average load | {scale['average_rows_per_s']:,} rows/s |
| Measured offline speed | {scale['measured_one_core_rows_per_s']:,} rows/s on one process |
| Cores needed | {scale['cores_average']} on average, {scale['cores_at_peak_assumption']} at the assumed peak ({scale['core_hours_per_day']} core-hours a day) |
| Offline latency per batch | {scale['seconds_per_batch_offline']} s |
| LLM calls | {scale['llm_calls_per_day']:,} a day, {scale['llm_requests_per_minute_average']} a minute on average |
| Hybrid LLM cost | ${scale['hybrid_llm_usd_per_day']:,} a day, ${scale['hybrid_llm_usd_per_year']:,} a year |
| LLM on every row for the {scale['llm_only_cells_priced']} priced checks | ${fmt(scale['llm_only_usd_per_day'], 2)} a day |
| One-time schema mapping | About ${fmt(scale['schema_mapping_one_time_usd_estimate'], 2)} for {scale['customers']} customers, using the measured schema-review call as a proxy. Not prototyped. |

### What changes at this scale

1. **Schemas become per-customer contracts.** 120 schemas can't share one column list. An LLM can propose a mapping once at onboarding, a person approves it, and it is stored as a versioned contract. Runtime checks then stay rules, with no LLM on the hot path.
2. **Reference tables become per-customer.** ZIP-borough and descriptor allow-lists are specific to this dataset. Each customer needs its own learned lookups with drift-based refresh, or allow-list false alarms grow as new categories appear.
3. **Checks run per customer, in parallel.** Batches shard by customer so one bad feed can quarantine itself. Null-spike and duplicate-rate baselines must be per customer and per segment.
4. **Near-duplicate windows need state across batches.** A batch-local check misses pairs that straddle a batch boundary, so this needs a keyed store with a short retention window. This is not built or measured here.
5. **LLM review needs paid capacity, a budget and a queue.** The free tier allowed 20 requests a day on `gemini-3.6-flash` and is unusable here. Review should run asynchronously with a per-customer budget, so dashboards are gated by the deterministic checks and never wait on the LLM.
6. **Personal data must not reach a third-party LLM by default.** Tests here use synthetic personal data. In production, text needs a data-processing agreement and redaction first, or the PII check stays local. That constraint can overrule a recall advantage for LLM review.
7. **Alert volume becomes the limit.** Row-level false alarms multiply with volume, so noisy checks should alert once per batch with samples, and go to a review queue rather than paging anyone.

### Not measured

Multi-schema behaviour, cross-batch state, sustained throughput, cloud compute cost, and LLM cost for customers with wider rows. All of these need a pilot before the numbers above are relied on.

## Where AI output was wrong

These figures come from development runs on a partial split, before the fixes.

- **IsolationForest scored 0% on swapped coordinates:** the first statistical detector, written by the AI, missed every swap at both rates while alerting on 80% of clean batches. Swapped points are far outside the training range but don't get shorter isolation paths than the tail threshold. The per-problem table caught it, and a robust z-score replaced it.
- **The first PII checks mistook agency help lines for personal data:** the rule flagged 3.28% of clean rows, and the rarity threshold rose so high that it detected 0%. Reading the top-scoring rows showed templates containing agency phone numbers and mailboxes, so repeated contacts are now allow-listed from the reference period.
"""


def main() -> None:
    detection, pipeline, profile = load("b_detection.json"), load("b_pipeline.json"), load("b_profile.json")
    scale = project(detection, pipeline)
    (RESULTS_DIR / "b_scale.json").write_text(json.dumps(scale, indent=1) + "\n")
    (ROOT / "RESULTS_B.md").write_text(report(detection, pipeline, profile, scale))
    print(json.dumps(scale, indent=1))


if __name__ == "__main__":
    main()
