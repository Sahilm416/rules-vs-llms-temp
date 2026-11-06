"""Build RESULTS_A.md from results/a_*.json so every number in it comes from a measurement file."""
from __future__ import annotations

import json
from pathlib import Path

from common.config import RESULTS_DIR, ROOT

TEMPLATE = Path(__file__).parent / "RESULTS_A.template.md"
NOT_MEASURED = "not measured"


def _load(name: str) -> dict:
    path = RESULTS_DIR / name
    return json.loads(path.read_text()) if path.exists() else {}


def _pct(part: int, whole: int) -> str:
    return f"{part}/{whole} ({100 * part / whole:.1f}%)" if whole else NOT_MEASURED


def comparison_table(fy: str, comparison: dict) -> str:
    section = comparison.get(fy, {})
    rows = [
        "| Implementation | Rupee-exact | Deterministic | Latency p50 / p95 | Cost per 1,000 requests | Every rupee traces to a clause |",
        "|---|---|---|---|---|---|",
    ]
    names = {"rules": "(a) Hand-coded rules", "compiled_raw": "(c) LLM-compiled, raw output", "compiled_reviewed": "(c) LLM-compiled, reviewed"}
    determinism = comparison.get("determinism", {})
    for key, value in section.items():
        if key in names:
            rows.append(
                f"| {names[key]} | {_pct(value['exact'], value['n'])} | Yes, {value['repeat_inputs']} inputs x 10 repeats | "
                f"{value['latency_ms_p50']:.3f} / {value['latency_ms_p95']:.3f} ms | $0 LLM | {_pct(value['traceable'], value['n'])} |"
            )
        else:
            model = key.split(":", 1)[1]
            sample = f" (sample of {value['suite_size']})" if value["n"] < value["suite_size"] else ""
            repeats = determinism.get(model, []) if fy == "2024-25" else []
            if repeats:
                varied = sum(r["distinct_tax_answers"] > 1 for r in repeats)
                text = sum(r["distinct_full_answers"] > 1 for r in repeats)
                det = f"Tax figures varied on {varied}/{len(repeats)} inputs; full answer text varied on {text}/{len(repeats)}"
            else:
                det = NOT_MEASURED
            rows.append(
                f"| (b) LLM at query time, {model} | {_pct(value['exact'], value['n'])}{sample} | {det} | "
                f"{value['latency_s_p50']:.1f} / {value['latency_s_p95']:.1f} s | ${value['cost_per_1000_usd']:.2f} at paid rates | {_pct(value['traceable'], value['n'])} |"
            )
    return "\n".join(rows)


def determinism_table(comparison: dict) -> str:
    rows = ["| Model | Input | Repeats | Distinct tax answers | Distinct full answers | All correct |", "|---|---|---|---|---|---|"]
    for model, items in comparison.get("determinism", {}).items():
        for item in items:
            rows.append(f"| {model} | {item['id']} | {item['repeats']} | {item['distinct_tax_answers']} | {item['distinct_full_answers']} | {item['all_correct']} |")
    return "\n".join(rows)


def stale_table(stale: dict) -> str:
    rows = [
        "| Implementation | FY 2025-26 requests on FY 2024-25 rules | Silently wrong | Wrong recommendation | Worst new-regime error | Unknown year is loud? |",
        "|---|---|---|---|---|---|",
    ]
    for name, label in (("rules", "(a) Rules, year forced to old config"), ("compiled", "(c) Compiled, year forced to old module")):
        value = stale.get(name)
        if value:
            rows.append(f"| {label} | {value['n']} | {_pct(value['silently_wrong'], value['n'])} | {value['wrong_recommendation']} | Rs {value['worst_new_regime_error_rupees']:,} | {'Yes, raises' if value['loud_on_unknown_year'] else 'No'} |")
    for key, value in stale.items():
        if key.startswith("query:"):
            rows.append(f"| (b) Query time, {key.split(':', 1)[1]}, given old rule text | {value['n']} | {_pct(value['silently_wrong'], value['n'])} | {NOT_MEASURED} | {NOT_MEASURED} | No: it answers with whatever text it is given |")
    return "\n".join(rows)


def parser_table(parser: dict) -> str:
    rows = [
        "| Design | All correct | Complete: exact, no question | Over-asked | Wrong silently | Must ask: right question | Guessed instead of asking |",
        "|---|---|---|---|---|---|---|",
    ]
    labels = {
        "rule": "Regex only", "llm_only": "LLM only (its values, its questions)", "hybrid": "Hybrid (LLM facts, verified quotes, code decides)",
        "hybrid_union": "Hybrid + regex: ask if either asks (in-sample, designed after seeing failures)",
    }
    for key, label in labels.items():
        s = parser.get(key, {}).get("summary")
        if s:
            rows.append(f"| {label} | {_pct(s['correct'], s['n'])} | {s['complete_correct']}/{s['complete_n']} | {s['over_asked']} | {s['wrong_silently']} | {s['must_ask_right_question']}/{s['must_ask_n']} | {s['guessed']} |")
    return "\n".join(rows)


def _design_values(comparison: dict, stale: dict, parser: dict) -> dict:
    """Numbers quoted in the prose, so the text can't drift from the measurements."""
    fy24, fy25 = comparison["2024-25"], comparison["2025-26"]
    rules_n = fy24["rules"]["n"] + fy25["rules"]["n"]
    q36 = fy24.get("query:gemini-3.6-flash", {})
    q35 = fy24.get("query:gemini-3.5-flash-lite", {})
    q25 = fy25.get("query:gemini-3.5-flash-lite", {})
    summary = lambda name: parser[name]["summary"]
    return {
        "{{RULES_N}}": str(rules_n),
        "{{RULES_MS}}": f"{fy24['rules']['latency_ms_p50']:.2f}",
        "{{RAW24}}": _pct(fy24["compiled_raw"]["exact"], fy24["compiled_raw"]["n"]),
        "{{RAW25}}": _pct(fy25["compiled_raw"]["exact"], fy25["compiled_raw"]["n"]),
        "{{RAW25_WRONG}}": str(fy25["compiled_raw"]["n"] - fy25["compiled_raw"]["exact"]),
        "{{STALE_WRONG}}": str(stale["rules"]["silently_wrong"]),
        "{{STALE_N}}": str(stale["rules"]["n"]),
        "{{STALE_WORST}}": f"{stale['rules']['worst_new_regime_error_rupees']:,}",
        "{{STALE_RECO}}": str(stale["rules"]["wrong_recommendation"]),
        "{{Q25_WRONG}}": str(q25.get("silent_wrong", NOT_MEASURED)),
        "{{Q25_N}}": str(q25.get("n", NOT_MEASURED)),
        "{{Q36_S}}": f"{q36['latency_s_p50']:.1f}" if q36 else NOT_MEASURED,
        "{{Q36_TRACE}}": f"{q36.get('traceable')}/{q36.get('n')} (`gemini-3.6-flash`)",
        "{{Q35_TRACE}}": f"{q35.get('traceable')}/{q35.get('n')} (`gemini-3.5-flash-lite`)",
        "{{LLM_CORRECT}}": f"{summary('llm_only')['correct']}/{summary('llm_only')['n']}",
        "{{RULE_CORRECT}}": f"{summary('rule')['correct']}/{summary('rule')['n']}",
        "{{H_GUESS}}": str(summary("hybrid")["guessed"]),
        "{{U_GUESS}}": str(summary("hybrid_union")["guessed"]),
        "{{H_OVER}}": str(summary("hybrid")["over_asked"]),
        "{{U_OVER}}": str(summary("hybrid_union")["over_asked"]),
        "{{COMPLETE_N}}": str(summary("hybrid")["complete_n"]),
        "{{PARSE_100K}}": f"{100 * parser['llm']['cost_per_1000_usd']:,.0f}",
        "{{Q36_100K}}": f"{100 * q36['cost_per_1000_usd']:,.0f}" if q36 else NOT_MEASURED,
    }


def main() -> None:
    comparison, stale, parser = _load("a_comparison.json"), _load("a_stale.json"), _load("a_parser.json")
    timing, official = _load("a_task5_timing.json"), _load("a_official.json")
    text = TEMPLATE.read_text()
    replacements = {
        "{{TABLE_FY24}}": comparison_table("2024-25", comparison),
        "{{TABLE_FY25}}": comparison_table("2025-26", comparison),
        "{{TABLE_DETERMINISM}}": determinism_table(comparison),
        "{{TABLE_STALE}}": stale_table(stale),
        "{{TABLE_PARSER}}": parser_table(parser),
        "{{TASK5_TIMING}}": "\n".join(f"- **{v['label']}:** {v['summary']}" for v in timing.get("implementations", [])),
        "{{OFFICIAL_CHECKED}}": str(official.get("checked", 0)),
        "{{OFFICIAL_TOTAL}}": str(official.get("worksheet_cases", 0)),
        "{{OFFICIAL_MISMATCHES}}": str(len(official.get("mismatches", []))),
    }
    replacements.update(_design_values(comparison, stale, parser))
    for key, value in replacements.items():
        text = text.replace(key, value)
    (ROOT / "RESULTS_A.md").write_text(text)


if __name__ == "__main__":
    main()
