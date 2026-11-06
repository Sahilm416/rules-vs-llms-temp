# Project A results: income-tax engine

**Recommendation:** ship a rules engine for every rupee and use an LLM only to extract facts from free text. Rules were rupee-exact on all {{RULES_N}} cases across both years, in {{RULES_MS}} ms and with no LLM cost. Query-time LLM was never measured on the full suite, and the cheap model's samples were mostly wrong with no error raised.

## What is and isn't verified

- **Official calculator: {{OFFICIAL_CHECKED}} of {{OFFICIAL_TOTAL}} worksheet cases checked, so the brief's 30-case requirement is not yet met.** The e-Filing calculator answered headless Chrome with "Permission Denied!!", and that block was not bypassed. A person must fill in `project_a/tests/official_check_worksheet.csv`, then run `python -m project_a.check_official`. Mismatches so far: {{OFFICIAL_MISMATCHES}} (none can exist until rows are filled in).
- **What supports expected values today:** an independent oracle (`tests/oracle.py`) that shares no code or config with the implementations, validated against 20 hand-worked cases. An AI wrote both the oracle and the engine, so they could share a misreading of the law. Only the official check rules that out.
- **Query-time samples are small.** The free tier allows 20 requests a day per model on `gemini-3.6-flash`. Those results are not an estimate of full-suite accuracy.
- **Rounding convention:** expected tax applies ss.288A and 288B. The official calculator's display convention could not be observed, so the check accepts a match to either the rounded or the unrounded figure.

## Comparison: FY 2024-25 (AY 2025-26)

{{TABLE_FY24}}

## Comparison: FY 2025-26 (AY 2026-27)

{{TABLE_FY25}}

Rupee-exact means tax payable under both regimes and the recommendation all match. "At paid rates" uses recorded tokens and Google's list prices; actual spend was $0 on the free tier. Rules and compiled latency is in-process compute only. `gemini-3.8-flash` returned 503 throughout, so it has no results. The compile itself cost one call per year (see `impl_compiled/raw/MODELS.json`).

## Determinism: repeated identical LLM calls (temperature 0)

{{TABLE_DETERMINISM}}

Even when `gemini-3.6-flash` repeated the same tax figures, the full answer differed between runs, so temperature 0 did not make the audit trail repeatable. `gemini-3.5-flash-lite` returned different tax figures for the same input.

## Plain-language parser (50 descriptions, including Hinglish, incomplete and contradictory)

{{TABLE_PARSER}}

The labels were written before any parser existed, but the same author wrote the regex parser after seeing them, so its score is likely flattering. There is no separate holdout set. D40 ("12 LPA, which is 1.5 lakh per month") is a contradiction that every design missed.

## Task 5: the law changes

### Time taken and what broke

{{TASK5_TIMING}}

Raw compiled accuracy fell from {{RAW24}} on FY 2024-25 to {{RAW25}} on FY 2025-26. The model also changed between those compiles because of quota, so the year and the model can't be separated as causes. See `project_a/impl_compiled/REVIEW_LOG.md` for each defect.

### Silent failures

{{TABLE_STALE}}

- **Stale rules are the most dangerous failure.** If a request reaches last year's rules, {{STALE_WRONG}} of {{STALE_N}} FY 2025-26 answers are wrong with no error, by up to Rs {{STALE_WORST}}, and {{STALE_RECO}} recommend the wrong regime. (a) and (c) prevent this by raising an error on a year they don't cover; the table's rows force the old year to show what that guard stops.
- **The raw FY 2025-26 compile was silently wrong on {{RAW25_WRONG}} cases.** It raised no error and passed the safety check. The frozen suite and review caught it. Marginal relief was the main cause, for example old-regime tax overstated by Rs 1,36,490 at Rs 50,00,010 of total income.
- **Query time has no equivalent guard:** it answers from whatever text it is given and raises nothing when wrong. On the FY 2025-26 sample, `gemini-3.5-flash-lite` was silently wrong on {{Q25_WRONG}} of {{Q25_N}}.

## Final design for 100,000 users

| Component | Label | Why (measurement) |
|---|---|---|
| Tax computation | **Rule** | {{RULES_N}}/{{RULES_N}} rupee-exact, deterministic, {{RULES_MS}} ms against {{Q36_S}} s p50 for `gemini-3.6-flash`, with no LLM cost |
| Rule authoring | **Hybrid**: person writes or reviews config, LLM optionally drafts | Raw compile ranged from {{RAW24}} to {{RAW25}}, and was silently wrong in the second year, so it can't ship unreviewed |
| Explanation and citations | **Rule** | Every rupee reconciles on {{RULES_N}}/{{RULES_N}}. Query-time answers varied between identical calls, and traced correctly on only {{Q36_TRACE}} and {{Q35_TRACE}} of samples |
| Fact extraction from free text | **Hybrid**: LLM extracts and quotes, code verifies the quote and recomputes rupees | LLM {{LLM_CORRECT}} against regex {{RULE_CORRECT}}; a quote missing from the text becomes a question |
| Decision to ask or answer | **Rule** with both extractors feeding it | Guessing fell from {{H_GUESS}} (hybrid) to {{U_GUESS}} (either asks), but over-asking rose from {{H_OVER}} to {{U_OVER}} of {{COMPLETE_N}}. A wrong rupee figure costs more than a question, so we accept this. In-sample: the design came after seeing failures |
| Number parsing | **Rule** | `money.py` is deterministic and unit tested |
| LLM outage fallback | **Rule** | The regex parser with the same policy can only add questions; it never changes how a rupee is computed |

**Cost:** per 100,000 requests, parsing costs about ${{PARSE_100K}} at paid rates and computation costs no LLM spend. Query-time computation on `gemini-3.6-flash` would add about ${{Q36_100K}} per 100,000. The free tier can't serve this load, so production needs a paid tier for parsing. Actual traffic per user is an assumption to confirm.

### Keeping it correct through the next Budget

1. **Budget day:** freeze the current year. Config is per financial year and an unknown year raises an error, so an uncovered year can't be answered silently.
2. **Write the new test cases first** from the Finance Bill and Memorandum, including hand-worked threshold cases and new slab boundaries, independently of the config.
3. **Change only config**, with a person reviewing a diff against the Memorandum. An LLM may draft it, but it never ships without the suite and a review.
4. **Check against the official calculator** once it supports the new year, before release.
5. **Re-issue when the Bill becomes an Act.** Treat the enacted text as a new version, because Parliament can amend it between Bill and Act.
6. **Keep old years running** for prior-year filings, and record the rule version with each answer.

## Assumptions and scope

- Resident individual with salary income only. Anything else triggers a question, not an answer.
- **s.24(b):** the Rs 2,00,000 limit assumes a loan taken on or after 1 April 1999 for purchase or construction. The Rs 30,000 cap for repairs or older loans is not modelled.
- **s.80D:** the self and family limit rises to Rs 50,000 based on the taxpayer's age only. The official rule covers any insured senior, including a spouse, and this is not modelled. Preventive check-up sub-limits and the medical-expenditure alternative are also not modelled.
- Regime ties go to the new regime, the default. Professional tax and s.80CCD(2) are outside the brief's scope list.

## Sources

Finance (No. 2) Bill 2024 Memorandum pp. 8-14 and Bill clauses 10 and 37; Finance Bill 2025 Memorandum pp. 6-11 and clause 20 (indiabudget.gov.in); Income Tax Department help and guidance pages for slabs, surcharge, deduction limits and the HRA formula (incometax.gov.in, incometaxindia.gov.in). The HRA formula comes from departmental guidance; the text of Rule 2A itself was not retrieved. Gemini prices are from aistudio.google.com/docs/pricing, read on 2026-11-06.

## Reproduce

`python -m pytest project_a` runs the tests. `python -m project_a.evaluate_parser`, `python -m project_a.evaluate`, `python -m project_a.check_official` and `python -m project_a.report` rebuild this file from recorded LLM calls, with no API key needed.
