# Review log for LLM-compiled rules

`raw/` is the model's output byte for byte. `reviewed/` is what ships. `raw/MODELS.json` records the model for each year.

**Who reviewed:** Claude Code (an AI agent) did this review, reading each module against the rule text and running the frozen suite. No human has reviewed these modules yet. The candidate must read them and re-review before relying on or presenting this log as their own.

## FY 2024-25, compiled by gemini-3.6-flash

Raw output scored full marks on the numeric suite. One defect the numeric tests could not see:

| # | Defect | Effect | Fix |
|---|---|---|---|
| 1 | In the new regime, the zero-value "not allowed" rows cited the denied section (such as `S80C`) instead of the denying clause `S115BAC-2` (6 rows) | Wrong citation, correct rupees: an audit reader is pointed at the wrong clause | Re-cited to `S115BAC-2` |

Noted, not changed: every rate and limit is hard-coded across the module, so each Budget means regenerating it or editing it in several places.

## FY 2025-26, compiled by gemini-3.5-flash-lite

`gemini-3.6-flash` had hit its free-tier daily limit and `gemini-3.8-flash` kept returning 503, so this year was compiled by the cheaper model. Because the year and the model both changed, this does not show which of the two caused the drop in raw accuracy.

| # | Defect | Effect | Silent? | Fix |
|---|---|---|---|---|
| 1 | Marginal relief used the current band's surcharge rate for an income of exactly T, instead of the band below (50L should be 0%, 1Cr 10%, 2Cr 15%, 5Cr 25%) | Tax overstated above surcharge thresholds, for example by Rs 1,36,490 at Rs 50,00,010 of old-regime income | Yes | Rate looked up by T |
| 2 | HRA limits were truncated to whole rupees, and used the binary float `Decimal(0.10)` | Rs 10 error on an odd-rupee salary | Yes | Exact `Decimal("0.10")`, no truncation |
| 3 | Rounding helper rounded paise up; ss.288A/288B drop paise first | Possible Rs 10 errors at digit boundaries | Yes | `ROUND_FLOOR` |
| 4 | House-property row showed the full interest even when salary could not absorb it, and the s.80A(2) cap had no row (body was `pass`) | Trace did not reconcile on 2 cases | Yes, in the audit trail only | Row shows what was set off; `S80A-2` row added |

Noted, not changed: this module uses binary floats for tax arithmetic although the prompt forbade them. It passes the frozen suite, so this is a residual risk rather than an observed error.
