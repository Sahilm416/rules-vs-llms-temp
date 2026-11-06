"""Check that an answer's rupees trace back to real clauses. Used for all three implementations."""
from __future__ import annotations

import re
from pathlib import Path

RULES_DIR = Path(__file__).parent / "rules_text"
TOLERANCE = 0.011  # trace amounts are stored to the paisa, so sums can drift by rounding


def rule_text(fy: str) -> str:
    return (RULES_DIR / f"fy{fy.replace('-', '_')}.md").read_text()


def known_clauses(fy: str) -> set[str]:
    return set(re.findall(r"\[([A-Z0-9][A-Za-z0-9-]*)\]", rule_text(fy)))


def check_regime(regime_result: dict, clauses: set[str]) -> list[str]:
    """Return problems: empty means every rupee reconciles and every citation exists in the rule text."""
    problems = []
    trace = regime_result.get("trace") or []
    if not trace:
        return ["no trace"]
    for row in trace:
        if row.get("clause") not in clauses:
            problems.append(f"unknown clause {row.get('clause')!r}")
    income = sum(r.get("amount", 0) for r in trace if r.get("group") == "income")
    tax = sum(r.get("amount", 0) for r in trace if r.get("group") == "tax")
    # Each row is stored to the paisa, so the sum can drift by up to about a paisa per row.
    slack = TOLERANCE * max(len(trace), 1)
    if abs(income - regime_result.get("total_income", 0)) > slack:
        problems.append(f"income lines sum to {income:.2f}, answer says {regime_result.get('total_income')}")
    if abs(tax - regime_result.get("tax_payable", 0)) > slack:
        problems.append(f"tax lines sum to {tax:.2f}, answer says {regime_result.get('tax_payable')}")
    return problems


def check_answer(answer: dict, fy: str) -> list[str]:
    clauses = known_clauses(fy)
    return [f"{r}: {p}" for r in ("old", "new") for p in check_regime(answer.get(r) or {}, clauses)]
