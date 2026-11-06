"""Deterministic Indian money parsing: '18 LPA', '1,50,000', '1.5L', '25k pm', 'dedh lakh', '2.1 Cr pa'."""
from __future__ import annotations

import re
from dataclasses import dataclass

_UNITS = {
    "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000, "lpa": 100_000, "l": 100_000,
    "k": 1_000, "thousand": 1_000, "hazaar": 1_000, "hazar": 1_000, "crore": 10_000_000, "crores": 10_000_000, "cr": 10_000_000,
}
_HINDI_WORDS = {"dedh": 1.5, "dhai": 2.5, "dhaai": 2.5, "sawa": 1.25, "paune": 0.75}
_UNIT_PATTERN = r"lakhs?|lacs?|lpa|crores?|cr|thousand|hazaar|hazar|l|k"

AMOUNT_RE = re.compile(
    rf"(?:(?:rs\.?|₹|inr)\s*)?(?<![\w.])(?P<num>\d[\d,]*(?:\.\d+)?|{'|'.join(_HINDI_WORDS)})\s*(?P<unit>{_UNIT_PATTERN})?(?![a-z0-9])",
    re.IGNORECASE,
)
_MONTHLY_RE = re.compile(r"per\s*month|/\s*month|\ba\s+month\b|\bpm\b|p\.m\.|\bmonthly\b|mahin[ae]|every month|/\s*mo\b", re.I)
_ANNUAL_RE = re.compile(
    r"per\s*annum|per\s*year|\bp\.?a\.?\b|\bannual(ly)?\b|\ba\s+year\b|\bsaal|\byearly\b|/\s*yr\b|/\s*year\b|\beach year\b|\bevery year\b|\blpa\b",
    re.I,
)


@dataclass
class Amount:
    rupees: int
    text: str
    start: int
    end: int
    period: str | None  # "month", "year" or None when the wording does not say


def _value(num: str, unit: str | None) -> int:
    base = _HINDI_WORDS.get(num.lower())
    if base is None:
        base = float(num.replace(",", ""))
    return round(base * _UNITS.get((unit or "").lower(), 1))


def find_amounts(text: str) -> list[Amount]:
    """All money-looking numbers. Bare numbers under 1000 are ignored: they are ages, percentages or section numbers."""
    amounts = []
    for match in AMOUNT_RE.finditer(text):
        unit = match.group("unit")
        rupees = _value(match.group("num"), unit)
        if not unit and rupees < 1000:
            continue
        tail = text[match.end() : match.end() + 25]
        period = None
        if unit and unit.lower() == "lpa":
            period = "year"
        elif _MONTHLY_RE.search(tail):
            period = "month"
        elif _ANNUAL_RE.search(tail):
            period = "year"
        amounts.append(Amount(rupees, match.group(0).strip(), match.start(), match.end(), period))
    return amounts


def parse_annual(evidence: str, assume_annual: bool = True) -> int | None:
    """Annual rupees from one quoted span. Monthly wording is multiplied by 12. None if no amount is present."""
    amounts = find_amounts(evidence)
    if not amounts:
        return None
    first = amounts[0]
    period = first.period
    if period is None and _MONTHLY_RE.search(evidence):
        period = "month"
    if period == "month":
        return first.rupees * 12
    return first.rupees if assume_annual or period == "year" else None
