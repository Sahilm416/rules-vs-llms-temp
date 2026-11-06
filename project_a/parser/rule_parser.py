"""Regex and keyword extractor: no LLM, instant, free, fully explainable, and limited to phrasings it anticipates."""
from __future__ import annotations

import re

from project_a.parser.money import find_amounts
from project_a.parser.policy import Profile, Slot

UNSUPPORTED_RE = re.compile(
    r"capital gain|side business|business income|my business|freelanc|\bnri\b|non[- ]resident|rental income|kiraye pe diya|rent aata|selling shares|sold shares",
    re.I,
)
METRO_RE = re.compile(r"\b(delhi|mumbai|bombay|kolkata|calcutta|chennai|madras)\b", re.I)
OTHER_CITY_RE = re.compile(r"\b(bengaluru|bangalore|pune|hyderabad|ahmedabad|noida|gurgaon|gurugram|jaipur|lucknow)\b", re.I)
BLANKET_NONE_RE = re.compile(
    r"\bno (other )?(deductions?|investments?)\b|zero deductions|nothing (else )?to claim|koi (aur )?deduction nahi|baaki (koi deduction nahi|kuch nahi)"
    r"|aur kuch deduction nahi|unka koi deduction nahi|no other deductions|nothing else|no deductions or investments|no tax-saving investments",
    re.I,
)
WORD_NUMBERS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
}
AGE_PATTERNS = [
    r"\bage(?:d| is|:)?\s*(\d{2})\b",
    r"\b(\d{2})\s*(?:-\s*)?(?:y\b|yrs?\b|years?\b|year[- ]old|saal\b)",
    r"\bi'?m\s+(?:a\s+)?(\d{2})\b",
    r"\bi am\s+(?:a\s+)?(\d{2})\b",
    r"\bturned\s+(\d{2})\b",
    r"\bbeing\s+(\d{2})\b",
    r"\bumar\s+(\d{2})\b",
    r"\bage\s+(\d{2})\s+hai\b",
    r"\bmain\s+(\d{2})\s+k[ai]\b",
    r"^\s*f,\s*(\d{2})\b",
]
PARENT_CONTEXT_RE = re.compile(r"parents?|mother|father|mummy", re.I)

# keyword -> field. Each pattern must be unambiguous about the deduction it names.
KEYWORDS = {
    "home_loan_interest": r"home[- ]?loan|housing loan",
    "sec_80ccd1b": r"\bnps\b|80ccd",
    "sec_80c": r"\b80c\b|\bppf\b|\belss\b|term insurance",
    "rent_paid": r"\brent\b|kiraya",
    "hra_received": r"\bhra\b",
}
NEGATION_RE = r"(?:\bno\b|\bnot\b|don'?t have|\bnil\b|\bzero\b|nahi|have made no|have no|without)"


def _clauses(text: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<=[.;|?!])\s+|\s*\|\s*|\n", text) if c.strip()]


def _merge(slot: Slot, status: str, value, evidence: str) -> None:
    """Combine findings. A stated amount against a denial, or two different amounts, is a conflict."""
    if slot.status == "unknown":
        slot.status, slot.value, slot.evidence = status, value, evidence
    elif slot.status == "value" and status == "value" and slot.value != value:
        slot.status = "conflict"
    elif {slot.status, status} == {"value", "none"}:
        slot.status = "conflict"


def _extract_age(text: str, p: Profile) -> None:
    ages = set()
    for clause in _clauses(text):
        pieces = re.split(r",\s*", clause)
        for piece in pieces:
            if PARENT_CONTEXT_RE.search(piece) and not re.search(r"\bpapa\b", piece, re.I):
                continue
            for pattern in AGE_PATTERNS:
                ages.update(int(a) for a in re.findall(pattern, piece, re.I))
    for word_tens, tens in WORD_NUMBERS.items():
        match = re.search(rf"\b{word_tens}(?:-| )(one|two|three|four|five|six|seven|eight|nine)\s+years?\s+old", text, re.I)
        if match and tens >= 20:
            ages.add(tens + WORD_NUMBERS[match.group(1).lower()])
    ages = {a for a in ages if 18 <= a <= 110}
    if not ages:
        return
    bands = {"below_60" if a < 60 else "60_to_79" if a < 80 else "80_plus" for a in ages}
    if len(ages) > 1:
        p.age_band.status = "conflict"
    else:
        p.age_band.status, p.age_band.value = "value", bands.pop()


def _extract_salary(text: str, p: Profile) -> None:
    claimed = {}
    for clause in _clauses(text):
        for piece in re.split(r"(?<=\d),\s+|;\s*", clause):
            lowered = piece.lower()
            is_salary_context = re.search(r"\bgross\b|\bsalary\b|\bsal\b|\blpa\b|\bpay\b|\bearn\b|p\.?a\.?\b|per annum", lowered)
            if not is_salary_context:
                continue
            if re.search(r"basic|\bhra\b|health|premium|rent\b|interest|\b80c\b|\bnps\b", lowered) and "gross" not in lowered and "lpa" not in lowered:
                continue
            for amount in find_amounts(piece):
                if re.search(r"basic|\bhra\b|of which", piece[: amount.start].lower()[-25:]):
                    continue
                period = amount.period
                if period is None and re.search(r"monthly|mahin", lowered):
                    period = "month"
                if period is None and re.search(r"annual|\byear\b|p\.?a\.?\b|saal", lowered):
                    period = "year"
                annual = amount.rupees * 12 if period == "month" else amount.rupees if period == "year" else None
                claimed[annual] = amount.text
                break
    unclear = re.search(r"in[- ]?hand|take[- ]?home|haath mein|\bctc\b", text, re.I)
    if unclear:
        p.gross_salary.status = "unknown"
        return
    stated = {a for a in claimed if a is not None}
    if len(stated) > 1:
        p.gross_salary.status = "conflict"
    elif len(stated) == 1 and re.search(r"\bgross\b|\bsal\b|\bpay\b|\bsalary\b", text, re.I):
        value = stated.pop()
        p.gross_salary.status, p.gross_salary.value, p.gross_salary.evidence = "value", value, claimed[value]


def _annual_near(piece: str, default_period: str = "year") -> int | None:
    amounts = find_amounts(piece)
    if not amounts:
        return None
    amount = amounts[0]
    period = amount.period or ("month" if re.search(r"mahin|monthly|\bmonth\b", piece, re.I) else default_period)
    return amount.rupees * 12 if period == "month" else amount.rupees


def _extract_deductions(text: str, p: Profile) -> None:
    for clause in _clauses(text):
        for piece in re.split(r",\s+|\s+and\s+|\s+but\s+|\s+aur\s+|:\s+", clause):
            lowered = piece.lower()
            negated = bool(re.search(NEGATION_RE, lowered))

            if re.search(r"health|medical|mediclaim|insurance|premium|\b80d\b", lowered) and "term insurance" not in lowered:
                is_parents = bool(re.search(r"parents?", lowered))
                name = "sec_80d_parents" if is_parents else "sec_80d_self"
                if negated and not re.search(r"\d", piece):
                    # "no health insurance" with no qualifier rules out both policies
                    _merge(getattr(p, name), "none", 0, piece)
                    if not is_parents and not re.search(r"apna|self|myself", lowered):
                        _merge(p.sec_80d_parents, "none", 0, piece)
                    continue
                amount = _annual_near(piece)
                if amount:
                    _merge(getattr(p, name), "value", amount, piece)
                elif re.search(r"\bnil\b|\bzero\b", lowered):
                    _merge(getattr(p, name), "none", 0, piece)
                continue

            for name, pattern in KEYWORDS.items():
                if not re.search(pattern, lowered):
                    continue
                slot = getattr(p, name)
                amount = _annual_near(piece) if re.search(r"\d", piece) or re.search(r"dedh|dhai", lowered) else None
                if amount:
                    _merge(slot, "value", amount, piece)
                elif negated:
                    _merge(slot, "none", 0, piece)
                break

            if re.search(r"basic", lowered):
                amount = _annual_near(piece)
                if amount:
                    _merge(p.basic_da, "value", amount, piece)

    # "no rent/hra" and "no rent or HRA" name two things at once.
    if re.search(r"\bno rent\s*(?:/|or|,|and)\s*hra\b|\bno hra\b|hra nahi", text, re.I):
        _merge(p.hra_received, "none", 0, "no hra")
    if re.search(r"\bno rent\b|rent nahi|rent bhi nahi|\bna rent\b|no (?:other )?deductions, rent", text, re.I):
        _merge(p.rent_paid, "none", 0, "no rent")
    if re.search(r"no\s+(?:home\s+)?loans?\b|koi loan nahi|\bna loan\b|or loans\b|home loan nahi", text, re.I):
        _merge(p.home_loan_interest, "none", 0, "no loan")
    if re.search(r"\bown my flat\b|\bparents' house\b", text, re.I):
        _merge(p.rent_paid, "none", 0, "owns or family home")
    if re.search(r"no insurance|koi insurance nahi|nps, insurance", text, re.I):
        _merge(p.sec_80d_self, "none", 0, "no insurance")
        _merge(p.sec_80d_parents, "none", 0, "no insurance")
    if re.search(r"no parents' policy|parents ka insurance nahi|parents have passed away|parents 80d nil", text, re.I):
        p.sec_80d_parents = Slot("none", 0, "no parents' policy")

    if BLANKET_NONE_RE.search(text):
        for name in ("rent_paid", "hra_received", "sec_80c", "sec_80ccd1b", "sec_80d_self", "sec_80d_parents", "home_loan_interest"):
            slot = getattr(p, name)
            if slot.status == "unknown":
                slot.status, slot.value = "none", 0


def _extract_flags(text: str, p: Profile) -> None:
    if METRO_RE.search(text):
        p.metro = Slot("value", True, METRO_RE.search(text).group(0))
    elif OTHER_CITY_RE.search(text):
        p.metro = Slot("value", False, OTHER_CITY_RE.search(text).group(0))
    if re.search(r"over 6\d|senior citizen hain|are (?:both )?(?:[6-9]\d)|both senior|parents.*\bsenior\b", text, re.I):
        p.parents_senior = Slot("value", True, "parents senior")
    elif re.search(r"in their (?:fifties|forties)|non[- ]senior", text, re.I):
        p.parents_senior = Slot("value", False, "parents not senior")


def parse(text: str) -> Profile:
    p = Profile()
    match = UNSUPPORTED_RE.search(text)
    if match:
        p.unsupported, p.unsupported_evidence = True, match.group(0)
    _extract_age(text, p)
    _extract_salary(text, p)
    _extract_deductions(text, p)
    _extract_flags(text, p)
    return p
