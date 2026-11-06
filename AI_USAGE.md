# AI usage

## Tools

| Tool | Used for |
|---|---|
| Claude Code (Claude Opus 5.5), including parallel sub-agents | Wrote nearly all code, tests, gold labels and reports in this repo: oracle, rules engine, parsers, injector, detectors, pipeline, and review of the compiled rules |
| Gemini free tier (`gemini-3.6-flash`, `gemini-3.5-flash-lite`) | The LLM under test: query-time tax computation, rule compilation, parsing and data-quality review. `gemini-3.8-flash` was tried and returned 503 throughout, so it has no results |

**Review:** the "you review them" step for compiled rules was carried out by Claude Code, as `project_a/impl_compiled/REVIEW_LOG.md` states.

**Independence limit:** the same AI wrote the oracle and the rules engine, so they could share a misreading of the law. Only the official calculator check can rule that out, and its status is reported in `RESULTS_A.md`.

## Where the AI was wrong, and how it was caught

**Claude Code wrote wrong expected values into the hand-worked test cases.** For three FY 2025-26 old-regime cases it first wrote 1,95,000, 1,97,600 and 2,23,600. The correct values are 1,87,200, 1,90,320 and 2,18,400. It caught them by redoing the arithmetic line by line before running any code. For example, at gross Rs 12,75,000: total income 12,25,000, tax 1,12,500 + 67,500 = 1,80,000, cess 7,200, total 1,87,200. Had these stayed in, the oracle would have correctly failed against them, but only after time was lost doubting the right code.

**Gemini wrote compiled rules that were silently wrong.** The raw FY 2025-26 compile from `gemini-3.5-flash-lite` passed the safety check and raised no errors, yet got 38 of 310 cases wrong. For example, it overstated old-regime tax by Rs 1,36,490 at a total income of Rs 50,00,010 because of a surcharge marginal-relief error. The frozen test suite caught this.

**Claude Code chose a detector that failed completely.** Its first IsolationForest scored 0% on swapped coordinates while alerting on 80% of clean batches. The per-problem results table caught it, and a robust z-score replaced it.

**A defect that numeric tests could not see.** The raw FY 2024-25 compile from `gemini-3.6-flash` scored 302/302, but its new-regime "not allowed" trace rows cited the section being denied, such as `S80C`, instead of the clause that denies it, `S115BAC-2`. Reading the code caught this, not testing, and that is why compiled rules need review even at 100% accuracy.
