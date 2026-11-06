# Project B results: data-quality checks

Reproduce the evaluation with `python -m project_b.evaluate offline && python -m project_b.evaluate merge && python -m project_b.pipeline && python -m project_b.scale`.

## Read this first

- **Data coverage:** rules, statistics, the hybrid pipeline and the profile use 365 days (2023-01-01 to 2023-12-31). 
- **LLM rows are from a partial year:** the LLM sample ran on 286 days (2023-01-01 to 2023-10-17) while the download was in progress, and was kept to save quota. It was not re-run, so **LLM rows and the other rows do not come from the same batches**. The split was confirmed by matching a rebuilt prompt to the recorded call. Treat LLM against rules or statistics as indicative, not a head-to-head.
- **LLM sample is small:** {"gemini-3.5-flash-lite": 36, "gemini-3.1-flash-lite": 0} calls. Intervals are 95% Wilson.  LLM cells were measured at a 5% injection rate on an enriched review list, so their recall is not comparable to a full-batch scan. One call per batch reviews only 0.8% of a 5,000-row batch.
- **Self-authored test:** the same AI session wrote the injector and detectors, and the near-duplicate rule and the descriptor allow-list threshold were changed after the injector was visible. The rule keyword lists predate it. Treat rule recall as an upper bound.
- **Clean batches are scrubbed:** rows with known real problems were removed first. Thresholds were fitted on the earlier period, but the null-spike column exclusions and PII allow-list were added after looking at clean-batch false alarms, so those false-alarm rates are slightly optimistic.
- **Cost:** LLM dollars are real token counts at list price; the calls were free-tier. Rules and statistics show $0 API, and their compute is not priced.
- **Clarity score:** One point each: names specific rows; names columns; states the observed value; states the expected value; gives a readable reason of 20+ characters. Mean over alerts, 0-5. Batch-level alerts about a whole column cannot name rows and lose that point unless they flag rows.

## Per-problem detection, false alarms and cost

`llm` rows: 286-day split, 5% injection, enriched review list, 1 clean call per problem. All other rows: 365-day split, whole batches, 5 trials.

| Problem | Family | Detection at 1% | Detection at 5% | Row precision at 1% | Clean row false alarms | Clean batches alerting | $ per 1M rows | Rows/s | Alert clarity (0-5) |
|---|---|---|---|---|---|---|---|---|---|
| renamed_dropped_column | rules | 100.0% | 100.0% | n/a | 0.00% | 0% | $0 API | 167,318,179 | 4 |
| renamed_dropped_column | stats | 100.0% | 100.0% | n/a | 0.00% | 0% | $0 API | 206,398,315 | 4 |
| renamed_dropped_column | llm | 100% of 2 batches, CI [0.342, 1.0] | not run | n/a | row rate n/a | 0 of 1 clean calls fired | $0.23 | 10.6 | 4 |
| type_change | rules | 100.0% | 100.0% | 100.0% | 0.00% | 0% | $0 API | 375,096 | 5 |
| type_change | stats | 100.0% | 100.0% | 100.0% | 0.00% | 0% | $0 API | 194,767 | 5 |
| type_change | llm | 50% of 2 batches, CI [0.095, 0.905] | not run | n/a | row rate n/a | 0 of 1 clean calls fired | $0.19 | 14.8 | 4 |
| date_format_switch | rules | 100.0% | 100.0% | 100.0% | 0.00% | 0% | $0 API | 1,378,553 | 5 |
| date_format_switch | stats | 100.0% | 100.0% | 100.0% | 0.00% | 0% | $0 API | 430,511 | 5 |
| date_format_switch | llm | 100% of 2 batches, CI [0.342, 1.0] | not run | n/a | row rate n/a | 0 of 1 clean calls fired | $0.19 | 13.2 | 4 |
| lat_lon_swap | rules | 100.0% | 100.0% | 100.0% | 0.00% | 0% | $0 API | 23,623,908 | 5 |
| lat_lon_swap | stats | 100.0% | 100.0% | 100.0% | 0.00% | 0% | $0 API | 25,200,546 | 5 |
| lat_lon_swap | llm | 100% of 21 reviewed rows, CI [0.845, 1.0] | not run | 100.0% | 0.0% of 99 reviewed | 0 of 1 clean calls fired | $74.52 | 11.3 | 5 |
| exact_duplicates | rules | 100.0% | 100.0% | 100.0% | 0.00% | 0% | $0 API | 510,739 | 5 |
| exact_duplicates | stats | 100.0% | 100.0% | 100.0% | 0.00% | 0% | $0 API | 503,874 | 5 |
| exact_duplicates | llm | 70% of 23 reviewed rows, CI [0.491, 0.844] | not run | 100.0% | 0.0% of 97 reviewed | 0 of 1 clean calls fired | $45.74 | 21.3 | 5 |
| near_duplicates | rules | 98.4% | 99.0% | 11.3% | 7.51% | 100% | $0 API | 970,908 | 5 |
| near_duplicates | stats | 86.8% | 85.9% | 7.3% | 11.28% | 100% | $0 API | 16,075 | 5 |
| near_duplicates | llm | 86% of 21 reviewed rows, CI [0.654, 0.95] | not run | 90.0% | 2.0% of 99 reviewed | 1 of 1 clean calls fired | $80.49 | 14.5 | 5 |
| null_spike | rules | 40.0% | 100.0% | 10.1% | 0.32% | 20% | $0 API | 294,849 | 5 |
| null_spike | stats | 80.0% | 100.0% | 12.5% | 0.32% | 20% | $0 API | 292,154 | 5 |
| null_spike | llm | 100% of 2 batches, CI [0.342, 1.0] | not run | n/a | row rate n/a | 0 of 1 clean calls fired | $0.2 | 16.8 | 4 |
| closed_before_created | rules | 100.0% | 100.0% | 100.0% | 0.00% | 0% | $0 API | 4,327,194 | 5 |
| closed_before_created | stats | 100.0% | 100.0% | 33.2% | 0.89% | 100% | $0 API | 1,935,028 | 5 |
| closed_before_created | llm | 100% of 22 reviewed rows, CI [0.851, 1.0] | not run | 100.0% | 0.0% of 98 reviewed | 0 of 1 clean calls fired | $72.24 | 14.7 | 5 |
| zip_borough_mismatch | rules | 99.2% | 99.5% | 100.0% | 0.00% | 0% | $0 API | 3,283,803 | 5 |
| zip_borough_mismatch | stats | 97.6% | 98.5% | 94.6% | 0.07% | 100% | $0 API | 1,047,274 | 5 |
| zip_borough_mismatch | llm | 100% of 24 reviewed rows, CI [0.862, 1.0] | not run | 100.0% | 0.0% of 96 reviewed | 0 of 1 clean calls fired | $46.56 | 18.6 | 5 |
| complaint_descriptor_mismatch | rules | 100.0% | 100.0% | 24.0% | 0.72% | 100% | $0 API | 2,558,919 | 5 |
| complaint_descriptor_mismatch | stats | 95.6% | 96.1% | 17.3% | 0.04% | 80% | $0 API | 79,843 | 5 |
| complaint_descriptor_mismatch | llm | 71% of 21 reviewed rows, CI [0.5, 0.862] | not run | 100.0% | 0.0% of 99 reviewed | 0 of 1 clean calls fired | $29.12 | 23 | 5 |
| resolution_status_contradiction | rules | 33.2% | 28.9% | 15.4% | 1.29% | 100% | $0 API | 954,368 | 5 |
| resolution_status_contradiction | stats | 48.0% | 50.3% | 96.0% | 0.04% | 80% | $0 API | 86,985 | 5 |
| resolution_status_contradiction | llm | 72% of 25 reviewed rows, CI [0.524, 0.857] | not run | 78.3% | 5.3% of 95 reviewed | 1 of 1 clean calls fired | $42.25 | 19 | 5 |
| pii_in_text | rules | 77.2% | 74.0% | 100.0% | 0.00% | 0% | $0 API | 42,211 | 5 |
| pii_in_text | stats | 100.0% | 100.0% | 87.4% | 0.20% | 100% | $0 API | 94,410 | 5 |
| pii_in_text | llm | 96% of 22 reviewed rows, CI [0.782, 0.992] | not run | 100.0% | 0.0% of 98 reviewed | 0 of 1 clean calls fired | $54.86 | 17.2 | 5 |

Batch-level problems report the share of corrupted batches detected; others report row recall. "Clean batches alerting" counts any flagged row, so one false row in 5,000 counts as an alerting batch.

## Hybrid pipeline, end to end

All 12 problems injected at once in 3 batches, plus 3 clean batches, on the 365-day split. Rates are 1%, except null spike at 5%. The decision to use the LLM rests on the 286-day sample above, while its calls in this run were made on the 365-day batches.

| Problem | Primary check | LLM confirms flags | Row recall | Recall if unreviewed rows are kept | Row precision | Batch alert | Clean batches alerting | Clean row false alarms | Left unreviewed |
|---|---|---|---|---|---|---|---|---|---|
| renamed_dropped_column | rules | no | 0.0% | 0.0% | n/a | 3/3 | 0/3 | 0.00% | 0 |
| type_change | rules | no | 98.7% | 98.7% | 100.0% | 3/3 | 0/3 | 0.00% | 0 |
| date_format_switch | rules | no | 100.0% | 100.0% | 60.5% | 3/3 | 0/3 | 0.00% | 0 |
| lat_lon_swap | rules | no | 98.7% | 98.7% | 100.0% | 3/3 | 0/3 | 0.00% | 0 |
| exact_duplicates | rules | no | 80.1% | 80.1% | 100.0% | 3/3 | 0/3 | 0.00% | 0 |
| near_duplicates | rules | yes | 2.0% | 82.0% | 42.9% | 3/3 | 3/3 | 0.11% | 972 |
| null_spike | stats | no | 100.0% | 100.0% | 88.8% | 3/3 | 2/3 | 3.87% | 0 |
| closed_before_created | rules | no | 100.0% | 100.0% | 100.0% | 3/3 | 0/3 | 0.00% | 0 |
| zip_borough_mismatch | rules | no | 66.0% | 66.0% | 100.0% | 2/3 | 0/3 | 0.00% | 0 |
| complaint_descriptor_mismatch | stats | yes | 56.2% | 76.5% | 100.0% | 3/3 | 1/3 | 0.01% | 40 |
| resolution_status_contradiction | stats | no | 15.0% | 15.0% | 92.0% | 1/3 | 3/3 | 0.03% | 0 |
| pii_in_text | stats | no | 33.3% | 33.3% | 68.9% | 3/3 | 3/3 | 0.13% | 0 |

- LLM confirms flags on: near_duplicates, complaint_descriptor_mismatch.
- LLM calls: 12 (2.0 per batch), 0 unavailable because of quota. LLM cost: **$0.89 per million rows**.
- Offline stages: 26,643 rows/s on one laptop process.
- Reviewing every row for every LLM-priced check would cost about $446.59 per million rows (12 checks priced).
- **The review cap costs recall.** Only 40 flagged rows per check are reviewed in each batch, and the rest raise no alert, so near-duplicate recall collapses when candidates far exceed the cap. Real repeat callers cause that excess. The "Recall if unreviewed rows are kept" column shows the recall if those rows stay as low-confidence flags. Reviewing all of them would take more calls per batch than the cost above, and was not measured.
- **Schema damage silences other checks.** The column hit in each mixed batch was: resolution_description (renamed); borough (dropped); resolution_description (renamed). Any check needing that column finds nothing in that batch, which lowers recall for ZIP, resolution and PII. The schema alert did fire in every mixed batch. Quarantining a batch on that alert is the recommended behaviour, but it isn't implemented here.
- **Later injections alter earlier ones.** An exact copy changed by a later problem is no longer exact, which lowers duplicate recall in this mixed test.

## Real issues in the raw data

| Issue | Rows | Share | Example |
|---|---|---|---|
| closed before created | 4,313 | 0.134% | {"unique_key": "56430946", "created_date": "2023-01-03T09:17:00.000", "closed_date": "2022-12-29T09:17:00.000", "agency": "DOT", "complaint_type": "St |
| closed equals created | 62,611 | 1.942% | {"unique_key": "56419266", "created_date": "2023-01-01T02:02:43.000", "closed_date": "2023-01-01T02:02:43.000", "agency": "DOHMH"} |
| closed in future | 0 | 0.0% | {} |
| closed status without closed date | 20,251 | 0.628% | {"unique_key": "56686328", "status": "Closed", "closed_date": null, "agency": "DSNY", "complaint_type": "Graffiti"} |
| open status with closed date | 6,875 | 0.213% | {"unique_key": "56421800", "status": "Unspecified", "closed_date": "2023-01-12T14:34:53.000", "agency": "DSNY", "complaint_type": "Missed Collection"} |
| due before created | 0 | 0.0% | {} |
| resolution update before created | 72,731 | 2.255% | {"unique_key": "56413194", "created_date": "2023-01-01T00:16:58.000", "resolution_action_updated_date": "2023-01-01T00:00:00.000", "agency": "HPD"} |
| missing coordinates | 48,579 | 1.506% | {"unique_key": "56418774", "agency": "NYPD", "complaint_type": "Illegal Fireworks", "incident_zip": "11220", "borough": "BROOKLYN"} |
| coordinates outside nyc box | 0 | 0.0% | {} |
| lat lon vs state plane disagree | 0 | 0.0% | {} |
| missing zip | 38,520 | 1.195% | {"unique_key": "56412433", "agency": "DOT", "complaint_type": "Traffic Signal Condition", "borough": "BROOKLYN"} |
| invalid zip | 223 | 0.007% | {"unique_key": "56460952", "incident_zip": "07740", "borough": "Unspecified", "agency": "DCWP"} |
| unspecified borough | 5,994 | 0.186% | {"unique_key": "56414169", "borough": "Unspecified", "incident_zip": null, "agency": "DOT"} |
| zip borough inconsistent | 1,614 | 0.05% | {"unique_key": "56413505", "incident_zip": "10463", "borough": "MANHATTAN", "agency": "NYPD"} |
| near duplicates | 156,701 | 4.859% | {"unique_key": "56417235", "created_date": "2023-01-01T00:07:26.000", "complaint_type": "Noise - Residential", "descriptor": "Loud Music/Party", "agen |
| created exactly at midnight | 2,439 | 0.076% | {"unique_key": "56416396", "created_date": "2023-01-01T00:00:00.000", "agency": "DOHMH", "complaint_type": "Food Poisoning"} |
| closed status pending text candidates | 71,893 | 2.229% | {"unique_key": "56417406", "status": "Closed", "resolution_description": "The complaint you filed is a duplicate of a condition already reported by an |
| open status done text candidates | 7 | 0.0% | {"unique_key": "56717517", "status": "Open", "resolution_description": "The Department of Housing Preservation and Development inspected the following |

Other findings:

- **Duplicates:** 0 repeated unique keys, and 2,209 rows with the same content under a different key.
- **Published contacts look like personal data:** 108,678 rows match a phone pattern, but 108,538 are on repeated agency service lines. Only 140 phone rows and 10 email rows are candidates for manual review, and none is confirmed as personal data.
- **Placeholders and casing:** `descriptor` holds the literal `N/A` on 58,550 rows, and `complaint_type` has 13 groups of case variants across 708,627 rows.
- **Lifecycle nulls:** during development on a partial split, DHS `closed_date` was 51-90% null in clean evaluation batches against a 14% baseline. It depends on request age, so lifecycle columns are excluded from null-spike checks instead of being raised as alarms.

## Scale design: 50M rows a day, 120 customers

Assumes rows arrive evenly (416,667 per customer per day), in 5,000-row batches, at a 3x peak (not measured). This 44-column public dataset stands in for customer data.

| Measure | Projection |
|---|---|
| Batches per day | 10,000 |
| Average load | 579 rows/s |
| Measured offline speed | 26,643 rows/s on one process |
| Cores needed | 0.02 on average, 1 at the assumed peak (0.5 core-hours a day) |
| Offline latency per batch | 0.19 s |
| LLM calls | 20,000 a day, 13.9 a minute on average |
| Hybrid LLM cost | $44.5 a day, $16,242 a year |
| LLM on every row for the 12 priced checks | $22329.5 a day |
| One-time schema mapping | About $0.14 for 120 customers, using the measured schema-review call as a proxy. Not prototyped. |

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
