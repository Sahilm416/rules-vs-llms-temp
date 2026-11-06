# Decision matrix

One row per component or check, with the measurement behind each choice. Sample sizes and caveats are in `RESULTS_A.md` and `RESULTS_B.md`.

**How far to trust these numbers:**
- **Project A:** expected values come from an oracle checked against 20 hand-worked cases. The official calculator check isn't complete; `RESULTS_A.md` reports how many cases have been checked.
- **Project B:** the same AI session wrote the injector and detectors, so rule recall is an upper bound. LLM rows come from a smaller sample on a 286-day split, so comparisons with rules and statistics are indicative.
- **LLM costs:** dollars are recorded tokens at list price. Actual spend was on the free tier.
- **Throughput:** rows/s changes slightly on each run. Detection, false-alarm and cost figures reproduce exactly.

## Project A: income-tax engine

| Component | Choice | Measurement | Trade-off |
|---|---|---|---|
| Tax computation | **Rule** | 612/612 rupee-exact over both years at 0.27 ms with no LLM cost. Query-time LLM: 3/3 sampled on `gemini-3.6-flash` at 17.8 s and $16.66 per 1,000; 7/22 and 7/25 on `gemini-3.5-flash-lite` at about $3.60 per 1,000 | Every law change needs a person to edit config |
| Rule authoring | **Hybrid** | Raw compile scored 302/302 in one year and 272/310 in the next, with no error raised. Reviewed compile scored 310/310. The FY 2025-26 config needed 17 changed lines and no engine change | The two compiles used different models, so the year and the model can't be separated as causes |
| Explanation and clause trace | **Rule** | 612/612 reconcile to the rupee. Query-time traces passed on 2/3 and 7/22, and full answers varied across identical repeats | Explanations are templated |
| Unknown-year guard | **Rule** | Forcing FY 2025-26 requests onto old rules gives 245/310 silently wrong, up to Rs 1,43,000 off. Unmodified (a) and (c) raise an error. Query time was silently wrong on 7/10 given old text | None measured |
| Fact extraction from free text | **Hybrid** | LLM 43/50, hybrid 41/50, regex 39/50. Hybrid guessed on 2 of 28 must-ask cases, against 3 for LLM alone and 4 for regex. Cost about $1.24 per 1,000 | Hybrid scores below LLM alone overall in exchange for fewer guesses and verifiable quotes |
| Decision to ask or answer | **Rule** | Asking if either extractor asks cuts guesses to 1 but raises over-asking from 5 to 11 of 22 complete descriptions, and overall score falls to 37/50 | In-sample, with no holdout. Accepts more questions to avoid wrong rupee figures. D40's contradiction is still missed |
| Number normalising | **Rule** | Hybrid recomputes rupees in code from a quote verified against the text; unit tested | Unusual phrasings fall through to the LLM's value or a question |
| LLM outage fallback | **Rule** | Regex parser with the same policy: 39/50, 0 wrong silently on complete descriptions, with 4 guesses on must-ask cases | Asks more often than the LLM (7 over-asks against 4) |

## Project B: data-quality checks

Detection is at a 1% injection rate on the 365-day split, unless marked as an LLM sample.

| Check | Choice | Rules: detection / clean-row false alarms | Statistics: detection / false alarms | LLM sample | Why |
|---|---|---|---|---|---|
| Renamed or dropped column | **Rule** | 100% / 0% | 100% / 0% | 2/2 batches | Exact at near-zero cost, and the rule names the column |
| Column type change | **Rule** | 100% / 0% | 100% / 0% | 1/2 batches | The LLM missed one; rules run at about 370,000 rows/s |
| Date format switch | **Rule** | 100% / 0% | 100% / 0% | 2/2 batches | A regex is exact and costs nothing |
| Latitude and longitude swapped | **Rule** | 100% / 0% | 100% / 0% | 100% of 21 rows, $74.52 per 1M | The LLM adds cost and no detection. The first IsolationForest scored 0% and was replaced |
| Exact duplicates | **Rule** | 100% / 0% | 100% / 0% | 70% of 23 rows | A hash beats sampling, which can't see pairs outside its sample |
| Near-duplicates | **Hybrid** (rule + LLM) | 98.4% / 7.51%, 11.3% precision | 86.8% / 11.28% | 86% of 21 rows, 90% precision | The rule alone is too noisy because real repeat callers look alike. **Weak spot:** with a 40-row review cap, pipeline recall is 2%, or 82% if unreviewed rows stay as low-confidence flags |
| Null spike in one agency | **Statistical** | 40% / 0.32% | 80% / 0.32% | 2/2 batches | Doubles rule detection at a 1% rate; both reach 100% at 5%. **Weak spot:** alerted on 2 of 3 clean pipeline batches |
| Closed before created | **Rule** | 100% / 0% | 100% / 0.89% | 100% of 22 rows | The rule has no false alarms; statistics add some |
| ZIP inconsistent with borough | **Rule** | 99.2% / 0% | 97.6% / 0.07% | 100% of 24 rows, $46.56 per 1M | A frozen lookup is nearly perfect and free. Pipeline recall drops to 66% when the borough column is lost |
| Complaint inconsistent with descriptor | **Hybrid** (statistics + LLM) | 100% / 0.72%, 24% precision | 95.6% / 0.04% | 71% of 21 rows, 100% precision | Statistics have far fewer false alarms than the allow-list, and the LLM confirms flags. Pipeline recall is 56.2%, or 76.5% with unreviewed rows kept |
| Resolution contradicting status | **Statistical** for now | 33.2% / 1.29% | 48% / 0.04% | 72% of 25 rows, 78.3% precision | **The LLM has the best recall, but one call per batch reviews only 0.8% of rows**, so it isn't primary. This is the check most worth a larger LLM budget. Pipeline recall is 15% with schema damage in the mix |
| Personal data in free text | **Statistical** | 77.2% / 0% | 100% / 0.2% | 96% of 22 rows, $54.86 per 1M | Finds bare names that a regex misses, and sends no personal data to a third party. Pipeline recall is 33.3% with schema damage in the mix |
| Overall pipeline | **Hybrid** | n/a | n/a | $0.89 per 1M rows, 2 calls per batch | About 500 times cheaper than LLM review on every row ($446.59 per 1M), at about 27,000 rows/s for offline stages. Batch quarantine on schema alerts is recommended but not implemented |

## Where an LLM clearly earned its cost

1. **Free-text extraction:** 43/50 against 39/50 for regex, and regex likely flatters itself because its author had seen the labels.
2. **Confirming noisy flags:** near-duplicate precision rose from 11.3% for the rule to 90% in the LLM sample.
3. **Semantic contradiction:** the best recall on resolution against status, at 72% against 48%, although not yet affordable at full coverage.
4. **One-time compilation, only with review:** a useful draft, but silently wrong on 38 of 310 cases before review.
