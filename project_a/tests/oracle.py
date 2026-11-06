"""Independent reference calculator used only to produce the frozen expected values.

It deliberately shares nothing with the implementations: no config, no slab tables, no imports
from the engine. Each year and regime is written out as literal arithmetic using exact Fractions.
The oracle is itself validated against hand-worked cases in golden.py.
"""
from __future__ import annotations

from fractions import Fraction as F
from math import floor


def _round10(amount) -> int:
    """Sections 288A/288B: drop paise, then round to the nearest 10 with 5 going up."""
    rupees = floor(amount)
    last = rupees % 10
    return rupees - last + (10 if last >= 5 else 0)


def _old_slab(i: int, age: int) -> F:
    above_10l = F(30, 100) * max(i - 1000000, 0)
    middle = F(20, 100) * max(min(i, 1000000) - 500000, 0)
    if age >= 80:
        return middle + above_10l
    start = 300000 if age >= 60 else 250000
    return F(5, 100) * max(min(i, 500000) - start, 0) + middle + above_10l


def _new_slab_fy24(i: int) -> F:
    t = F(0)
    if i > 1500000:
        t += F(30, 100) * (i - 1500000)
        i = 1500000
    if i > 1200000:
        t += F(20, 100) * (i - 1200000)
        i = 1200000
    if i > 1000000:
        t += F(15, 100) * (i - 1000000)
        i = 1000000
    if i > 700000:
        t += F(10, 100) * (i - 700000)
        i = 700000
    if i > 300000:
        t += F(5, 100) * (i - 300000)
    return t


def _new_slab_fy25(i: int) -> F:
    t = F(0)
    if i > 2400000:
        t += F(30, 100) * (i - 2400000)
        i = 2400000
    if i > 2000000:
        t += F(25, 100) * (i - 2000000)
        i = 2000000
    if i > 1600000:
        t += F(20, 100) * (i - 1600000)
        i = 1600000
    if i > 1200000:
        t += F(15, 100) * (i - 1200000)
        i = 1200000
    if i > 800000:
        t += F(10, 100) * (i - 800000)
        i = 800000
    if i > 400000:
        t += F(5, 100) * (i - 400000)
    return t


def _surcharge_rate(i: int, regime: str) -> F:
    if i > 50000000:
        return F(25, 100) if regime == "new" else F(37, 100)
    if i > 20000000:
        return F(25, 100)
    if i > 10000000:
        return F(15, 100)
    if i > 5000000:
        return F(10, 100)
    return F(0)


def _regime(inp: dict, regime: str) -> dict:
    fy, age = inp["fy"], inp["age"]
    gross = inp["basic_da"] + inp["hra_received"] + inp["other_salary"]
    if regime == "old":
        salary = F(inp["basic_da"])
        rent_less = F(inp["rent_paid"]) - salary / 10
        hra = max(min(F(inp["hra_received"]), rent_less, salary * (F(1, 2) if inp["metro"] else F(2, 5))), F(0))
        after_hra = gross - hra
        std = min(after_hra, F(50000))
        house_loss = F(min(inp["home_loan_interest"], 200000))
        gti = max(after_hra - std - house_loss, F(0))
        ded = (
            F(min(inp["sec_80c"], 150000))
            + F(min(inp["sec_80ccd1b"], 50000))
            + F(min(inp["sec_80d_self"], 50000 if age >= 60 else 25000))
            + F(min(inp["sec_80d_parents"], 50000 if inp["parents_senior"] else 25000))
        )
        total = _round10(gti - min(ded, gti))
        slab = lambda x: _old_slab(x, age)
    else:
        hra = F(0)
        std = min(F(gross), F(75000))
        total = _round10(gross - std)
        slab = _new_slab_fy24 if fy == "2024-25" else _new_slab_fy25

    tax = slab(total)

    rebate = F(0)
    if regime == "old":
        if total <= 500000:
            rebate = min(tax, F(12500))
    else:
        limit, cap = (700000, 25000) if fy == "2024-25" else (1200000, 60000)
        if total <= limit:
            rebate = min(tax, F(cap))
        elif tax > total - limit:
            rebate = tax - (total - limit)
    after_rebate = tax - rebate

    rate = _surcharge_rate(total, regime)
    surcharge = after_rebate * rate
    if rate > 0:
        floor_t = 50000000 if total > 50000000 else 20000000 if total > 20000000 else 10000000 if total > 10000000 else 5000000
        at_t = slab(floor_t)
        ceiling = at_t * (1 + _surcharge_rate(floor_t, regime)) + (total - floor_t)
        if after_rebate + surcharge > ceiling:
            surcharge = ceiling - after_rebate
    cess = (after_rebate + surcharge) * F(4, 100)
    final = after_rebate + surcharge + cess
    return {
        "total_income": total,
        "slab_tax": float(tax),
        "rebate": float(rebate),
        "surcharge": round(float(surcharge), 2),
        "cess": round(float(cess), 2),
        "total_before_rounding": round(float(final), 2),
        "tax_payable": _round10(final),
    }


def compute(inp: dict) -> dict:
    old, new = _regime(inp, "old"), _regime(inp, "new")
    return {
        "old": old,
        "new": new,
        "recommended": "old" if old["tax_payable"] < new["tax_payable"] else "new",
    }
