"""The service: plain-language description in; a clarifying question or a traced tax answer out.

An LLM only extracts facts. Whether to ask, and every rupee, is decided by deterministic code. If the LLM is
unavailable the regex parser takes over, which can only cost extra questions because the same policy still applies.

CLI: python -m project_a.service "I'm 30, gross 12 LPA, no deductions" --fy 2024-25
"""
from __future__ import annotations

import argparse
import json

from project_a.impl_rules import engine
from project_a.parser import llm_parser, rule_parser
from project_a.parser.policy import clarify_topics, questions_for, to_tax_input


def _extract(text: str, use_llm: bool):
    """Return the profile to compute from, and the merged question topics."""
    rule_profile = rule_parser.parse(text)
    rule_topics, rule_conflicts = clarify_topics(rule_profile)
    if not use_llm:
        return rule_profile, rule_topics, rule_conflicts, "rule"
    try:
        profile = llm_parser.hybrid(text)
    except Exception:  # no key, no quota, network failure or an unusable reply
        return rule_profile, rule_topics, rule_conflicts, "rule_fallback"
    topics, conflicts = clarify_topics(profile)
    # Ask if either extractor sees a gap: a wrong rupee figure costs more than one extra question.
    merged = topics + [t for t in rule_topics if t not in topics]
    return profile, merged, conflicts + [c for c in rule_conflicts if c not in conflicts], "hybrid_union"


def why(result: dict) -> str:
    old, new = result["old"]["tax_payable"], result["new"]["tax_payable"]
    chosen = result["recommended"]
    if old == new:
        return f"Both regimes cost Rs {new:,}, so the new regime is recommended because it is the default [S115BAC-1A]."
    other = "new" if chosen == "old" else "old"
    saving = abs(old - new)
    regime = result[chosen]
    claimed = [f"{row['description']} [{row['clause']}]" for row in result["old"]["trace"] if row["group"] == "income" and row["amount"] < 0]
    text = f"The {chosen} regime costs Rs {regime['tax_payable']:,}, which is Rs {saving:,} less than the {other} regime [S115BAC-1A]."
    if chosen == "old":
        return f"{text} Your deductions outweigh the new regime's lower rates: {'; '.join(claimed)}."
    return f"{text} The old regime's deductions do not make up for the new regime's lower rates."


def answer(text: str, fy: str = "2024-25", followups: tuple[str, ...] = (), use_llm: bool = True) -> dict:
    """Follow-up answers are appended to the description and the whole text is parsed again."""
    full = " ".join((text, *followups))
    profile, topics, conflicts, parser_used = _extract(full, use_llm)
    if topics:
        return {"status": "need_info", "parser": parser_used, "topics": topics, "questions": questions_for(topics, conflicts)}
    inp = to_tax_input(profile, fy)
    result = engine.compute(inp)
    return {
        "status": "ok",
        "parser": parser_used,
        "input": inp,
        "old": result["old"],
        "new": result["new"],
        "recommended": result["recommended"],
        "why": why(result),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("text")
    parser.add_argument("--fy", default="2024-25")
    parser.add_argument("--answer", action="append", default=[], help="answer to an earlier clarifying question")
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()
    print(json.dumps(answer(args.text, args.fy, tuple(args.answer), not args.no_llm), indent=1, ensure_ascii=False))
