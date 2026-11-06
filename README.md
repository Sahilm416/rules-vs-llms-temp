# Rules vs LLMs: Fire AI take-home

Two systems, each built and measured three ways, to decide where a rule, a statistic or an LLM belongs.

| Deliverable | Where |
|---|---|
| Income-tax engine | `project_a/` |
| Data-quality layer | `project_b/` |
| Results and designs | `RESULTS_A.md`, `RESULTS_B.md` |
| Rule-vs-LLM decisions | `DECISION_MATRIX.md` |
| AI usage note | `AI_USAGE.md` |

## Run everything

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python run_all.py
```

LLM results replay from `llm_cache/`, so no key is needed to reproduce the numbers. The first run downloads NYC 311 data for 2023, about 3.2M rows, into `project_b/data/` (gitignored).

To make new LLM calls, set `GEMINI_API_KEY` in your environment. The Gemini free tier limits requests per model per day, so sample sizes in the results are reported as actually measured.

## Try the tax service

```bash
.venv/bin/python -m project_a.service "I'm 34 and my gross salary is 18 LPA. No rent, no HRA, no investments, no insurance and no home loan."
```

If the description is missing something or contradicts itself, the service asks a question instead of guessing.

## Official calculator checks

The e-Filing portal refuses automated browsers, so these checks are manual. Fill in `project_a/tests/official_check_worksheet.csv` from the [official calculator](https://eportal.incometax.gov.in/iec/foservices/#/TaxCalc/calculator), then run `.venv/bin/python -m project_a.check_official`. `RESULTS_A.md` reports how many have been checked.
