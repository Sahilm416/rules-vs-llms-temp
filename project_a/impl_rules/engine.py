"""Implementation (a): hand-coded rules. Logic only; all rates and limits live in fy*.toml.

Each computation step appends a trace line carrying its clause ID. An unknown financial year raises
instead of falling back, so a missing config can never produce a silently wrong answer.
"""
from __future__ import annotations

import tomllib
from decimal import ROUND_FLOOR, Decimal as D
from pathlib import Path

CONFIG_DIR = Path(__file__).parent


class UnsupportedYear(ValueError):
    pass


def load_config(fy: str) -> dict:
    path = CONFIG_DIR / f"fy{fy.replace('-', '_')}.toml"
    if not path.exists():
        raise UnsupportedYear(f"no rules configured for FY {fy}")
    return tomllib.loads(path.read_text())


def _round10(amount: D) -> int:
    rupees = int(amount.to_integral_value(rounding=ROUND_FLOOR))
    last = rupees % 10
    return rupees - last + (10 if last >= 5 else 0)


def _money(value: D) -> float:
    return round(float(value), 2)


def _slabs_for(regime_cfg: dict, age: int) -> list[dict]:
    return [band for band in regime_cfg["age_bands"] if age >= band["min_age"]][-1]["slabs"]


def _slab_tax(income: int, slabs: list[dict]) -> list[tuple[dict, D]]:
    """Tax in each slab that the income reaches, in order."""
    rows, lower = [], 0
    for slab in slabs:
        upper = slab.get("upto")
        if income <= lower:
            break
        portion = (min(income, upper) if upper is not None else income) - lower
        rows.append((slab, D(portion) * slab["pct"] / 100))
        lower = upper if upper is not None else income
    return rows


def _surcharge_pct(income: int, bands: list[dict]) -> int:
    return max((b["pct"] for b in bands if income > b["above"]), default=0)


def _compute_regime(inp: dict, cfg: dict, regime: str) -> dict:
    rc = cfg[regime]
    trace: list[dict] = []

    def line(group: str, clause: str, description: str, amount) -> None:
        trace.append({"group": group, "clause": clause, "description": description, "amount": _money(D(amount))})

    # Income under the head Salaries
    gross = inp["basic_da"] + inp["hra_received"] + inp["other_salary"]
    line("income", "S17", "Gross salary", gross)
    hra_exempt = D(0)
    if regime == "old":
        hra = cfg["hra"]
        salary = D(inp["basic_da"])
        pct = hra["metro_pct"] if inp["metro"] else hra["non_metro_pct"]
        hra_exempt = max(
            min(
                D(inp["hra_received"]),
                D(inp["rent_paid"]) - salary * hra["rent_excess_over_salary_pct"] / 100,
                salary * pct / 100,
            ),
            D(0),
        )
        if inp["hra_received"]:
            line("income", hra["clause"], "HRA exemption, least of the three limits", -hra_exempt)
    after_hra = D(gross) - hra_exempt
    standard = min(after_hra, D(rc["standard_deduction"]))
    line("income", "S16-ia", "Standard deduction", -standard)

    # House property loss, then Chapter VI-A, each limited by what is left
    income = after_hra - standard
    if regime == "old" and inp["home_loan_interest"]:
        allowed = min(D(inp["home_loan_interest"]), D(cfg["home_loan"]["cap"]))
        used = min(allowed, income)
        line("income", cfg["home_loan"]["clause"], "Home-loan interest on self-occupied house, set off against salary", -used)
        income -= used

    if regime == "old":
        for ded in cfg["deductions"]:
            amount = inp[ded["field"]]
            if not amount:
                continue
            cap = ded["cap"]
            if "senior_cap" in ded:
                senior = inp["age"] >= ded["senior_age"] if ded["senior_when"] == "self_age" else inp[ded["senior_when"]]
                cap = ded["senior_cap"] if senior else ded["cap"]
            used = min(D(min(amount, cap)), income)
            line("income", ded["clause"], f"Deduction, limit Rs {cap}", -used)
            income -= used

    total_income = _round10(income)
    line("income", "S288A", "Round total income to nearest Rs 10", D(total_income) - income)

    # Slab tax
    slabs = _slabs_for(rc, inp["age"])
    tax = D(0)
    for slab, amount in _slab_tax(total_income, slabs):
        line("tax", slab["clause"], f"Slab at {slab['pct']}%", amount)
        tax += amount

    # Section 87A
    reb = rc["rebate"]
    rebate = D(0)
    if total_income <= reb["income_limit"]:
        rebate = min(tax, D(reb["cap"]))
        rebate_clause = reb["clause"]
    elif reb["marginal_clause"] and tax > total_income - reb["income_limit"]:
        rebate = tax - (total_income - reb["income_limit"])
        rebate_clause = reb["marginal_clause"]
    if rebate:
        line("tax", rebate_clause, "Section 87A rebate", -rebate)
    after_rebate = tax - rebate

    # Surcharge with marginal relief
    bands = rc["surcharge"]
    pct = _surcharge_pct(total_income, bands)
    surcharge = after_rebate * pct / 100
    if pct:
        band = [b for b in bands if total_income > b["above"]][-1]
        line("tax", band["clause"], f"Surcharge at {pct}%", surcharge)
        threshold = band["above"]
        tax_at_threshold = sum((a for _, a in _slab_tax(threshold, slabs)), D(0))
        ceiling = tax_at_threshold * (100 + _surcharge_pct(threshold, bands)) / 100 + (total_income - threshold)
        relief = max(after_rebate + surcharge - ceiling, D(0))
        if relief:
            line("tax", "SURCH-MR", "Marginal relief on surcharge", -relief)
            surcharge -= relief

    cess = (after_rebate + surcharge) * cfg["cess"]["pct"] / 100
    line("tax", cfg["cess"]["clause"], f"Health and Education Cess at {cfg['cess']['pct']}%", cess)
    total = after_rebate + surcharge + cess
    payable = _round10(total)
    line("tax", "S288B", "Round tax payable to nearest Rs 10", D(payable) - total)

    return {
        "total_income": total_income,
        "slab_tax": _money(tax),
        "rebate": _money(rebate),
        "surcharge": _money(surcharge),
        "cess": _money(cess),
        "total_before_rounding": _money(total),
        "tax_payable": payable,
        "trace": trace,
    }


def compute(inp: dict) -> dict:
    cfg = load_config(inp["fy"])
    old, new = _compute_regime(inp, cfg, "old"), _compute_regime(inp, cfg, "new")
    return {"old": old, "new": new, "recommended": "old" if old["tax_payable"] < new["tax_payable"] else "new"}
