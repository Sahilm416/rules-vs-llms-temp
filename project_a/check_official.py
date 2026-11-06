"""Compare hand-entered official calculator results with our expected values.

Build the sheet: python -m project_a.check_official --build
Score it:        python -m project_a.check_official

The e-Filing calculator answered automated access with "Permission Denied!!", so a person must type these in.
This reports exactly how many rows were checked. Rows left blank count as not checked, never as passing.
A match means the portal's figure equals either our s.288B payable or our figure before that rounding,
because the portal's display convention could not be observed.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from common.config import RESULTS_DIR
from project_a.impl_rules import engine
from project_a.run_llm_calls import load_cases

SHEET = Path(__file__).parent / "tests" / "official_check_worksheet.csv"
COLUMNS = [
    "case_id", "assessment_year", "age", "gross_salary", "hra_exemption_old_regime_only", "sec_80c", "sec_80ccd1b",
    "sec_80d_self", "sec_80d_parents", "home_loan_interest_old_regime_only",
    "expected_old_payable", "expected_old_before_rounding", "expected_new_payable", "expected_new_before_rounding",
    "official_old", "official_new",
]
AY = {"2024-25": "2025-26", "2025-26": "2026-27"}
QUOTA = {"2024-25": 26, "2025-26": 14}


def _select(fy: str) -> list[dict]:
    """Take cases from every category in turn, so the sample covers every threshold family."""
    by_category: dict[str, list[dict]] = {}
    for case in load_cases(fy):
        by_category.setdefault(case["category"], []).append(case)
    picked: list[dict] = []
    depth = 0
    while len(picked) < QUOTA[fy]:
        for group in by_category.values():
            index = depth * max(len(group) // 3, 1)
            if index < len(group) and len(picked) < QUOTA[fy]:
                picked.append(group[index])
        depth += 1
    return picked


def build() -> int:
    rows = []
    for fy, _ in QUOTA.items():
        for case in _select(fy):
            inp, exp = case["input"], case["expected"]
            trace = engine.compute(inp)["old"]["trace"]
            hra = -sum(r["amount"] for r in trace if r["clause"] == "S10-13A")
            rows.append({
                "case_id": case["id"],
                "assessment_year": AY[fy],
                "age": inp["age"],
                "gross_salary": inp["basic_da"] + inp["hra_received"] + inp["other_salary"],
                "hra_exemption_old_regime_only": hra,
                "sec_80c": inp["sec_80c"],
                "sec_80ccd1b": inp["sec_80ccd1b"],
                "sec_80d_self": inp["sec_80d_self"],
                "sec_80d_parents": inp["sec_80d_parents"],
                "home_loan_interest_old_regime_only": inp["home_loan_interest"],
                "expected_old_payable": exp["old"]["tax_payable"],
                "expected_old_before_rounding": exp["old"]["total_before_rounding"],
                "expected_new_payable": exp["new"]["tax_payable"],
                "expected_new_before_rounding": exp["new"]["total_before_rounding"],
                "official_old": "",
                "official_new": "",
            })
    with SHEET.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def _matches(official: float, payable: float, before: float) -> bool:
    return abs(official - payable) < 0.5 or abs(official - before) < 1.0


def check() -> dict:
    rows = list(csv.DictReader(SHEET.open()))
    checked, mismatches = 0, []
    for row in rows:
        if not row["official_old"].strip() or not row["official_new"].strip():
            continue
        checked += 1
        old, new = float(row["official_old"].replace(",", "")), float(row["official_new"].replace(",", ""))
        if not _matches(old, float(row["expected_old_payable"]), float(row["expected_old_before_rounding"])):
            mismatches.append({"case": row["case_id"], "regime": "old", "official": old, "ours": float(row["expected_old_payable"])})
        if not _matches(new, float(row["expected_new_payable"]), float(row["expected_new_before_rounding"])):
            mismatches.append({"case": row["case_id"], "regime": "new", "official": new, "ours": float(row["expected_new_payable"])})
    result = {"worksheet_cases": len(rows), "checked": checked, "mismatches": mismatches}
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "a_official.json").write_text(json.dumps(result, indent=1) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    if parser.parse_args().build:
        print("cases written:", build())
    else:
        print(json.dumps(check(), indent=1))
