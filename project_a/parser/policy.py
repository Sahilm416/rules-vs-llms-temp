"""The structured profile, and the deterministic decision to answer or ask. Extractors only fill in the profile.

Each field has a status:
  value    stated, with an amount
  none     explicitly ruled out
  unknown  not stated, or mentioned without an amount
  conflict the text says two incompatible things
"""
from __future__ import annotations

from dataclasses import dataclass, field

MONEY_FIELDS = ("basic_da", "hra_received", "rent_paid", "sec_80c", "sec_80ccd1b", "sec_80d_self", "sec_80d_parents", "home_loan_interest")
DEDUCTIBLE = ("rent_paid", "sec_80c", "sec_80ccd1b", "sec_80d_self", "sec_80d_parents", "home_loan_interest")
AGE_FOR_BAND = {"below_60": 30, "60_to_79": 60, "80_plus": 80}
PARENT_CAP_WITHOUT_SENIOR = 25000

QUESTIONS = {
    "unsupported": "This calculator covers salary income of Indian residents only. Your description mentions other income or non-resident status, so I can't give a correct figure. Could you confirm whether you have only salary income as a resident?",
    "conflict": "Part of your description contradicts itself ({detail}). Which is correct?",
    "salary": "What is your gross annual salary from your Form 16 or payslip, before tax? In-hand pay or CTC isn't enough to compute this exactly. If you give a figure, please say whether it is per month or per year.",
    "age": "How old were you during the financial year? The old regime depends on whether you were under 60, 60 to 79, or 80 or above.",
    "hra_details": "To work out your HRA exemption I need your annual rent paid, annual HRA received, annual basic salary plus DA, and your city. Which of these can you give me?",
    "deductions": "Do you have any of these, and for how much per year: 80C investments, NPS under 80CCD(1B), health insurance for yourself, health insurance for your parents, home-loan interest, or rent? Please say 'none' if you have none.",
    "parents_age": "Is either of your parents aged 60 or above? This decides whether their health-insurance limit is Rs 25,000 or Rs 50,000.",
}


@dataclass
class Slot:
    status: str = "unknown"
    value: object = None
    evidence: str = ""


@dataclass
class Profile:
    gross_salary: Slot = field(default_factory=Slot)
    age_band: Slot = field(default_factory=Slot)
    basic_da: Slot = field(default_factory=Slot)
    hra_received: Slot = field(default_factory=Slot)
    rent_paid: Slot = field(default_factory=Slot)
    metro: Slot = field(default_factory=Slot)
    sec_80c: Slot = field(default_factory=Slot)
    sec_80ccd1b: Slot = field(default_factory=Slot)
    sec_80d_self: Slot = field(default_factory=Slot)
    sec_80d_parents: Slot = field(default_factory=Slot)
    parents_senior: Slot = field(default_factory=Slot)
    home_loan_interest: Slot = field(default_factory=Slot)
    unsupported: bool = False
    unsupported_evidence: str = ""

    def amount(self, name: str) -> int:
        slot = getattr(self, name)
        return slot.value if slot.status == "value" and slot.value else 0


def clarify_topics(p: Profile) -> tuple[list[str], list[str]]:
    """Return (topics to ask about, names of conflicting fields). Empty topics means the answer is safe to compute."""
    if p.unsupported:
        return ["unsupported"], []
    conflicts = [name for name in p.__dataclass_fields__ if isinstance(getattr(p, name), Slot) and getattr(p, name).status == "conflict"]
    if p.gross_salary.status == "value" and p.amount("basic_da") + p.amount("hra_received") > p.gross_salary.value:
        conflicts.append("basic_da")
    if conflicts:
        return ["conflict"], conflicts

    topics = []
    if p.gross_salary.status != "value":
        topics.append("salary")
    if p.age_band.status != "value":
        topics.append("age")

    rent, hra = p.rent_paid, p.hra_received
    pays_rent, gets_hra = rent.status == "value" and rent.value > 0, hra.status == "value" and hra.value > 0
    if pays_rent or gets_hra:
        needs_more = (pays_rent and hra.status == "unknown") or (gets_hra and rent.status == "unknown")
        if pays_rent and gets_hra and (p.basic_da.status != "value" or p.metro.status != "value"):
            needs_more = True
        if needs_more:
            topics.append("hra_details")

    unknown = [n for n in DEDUCTIBLE if getattr(p, n).status == "unknown"]
    if (pays_rent or gets_hra) and "rent_paid" in unknown and "hra_details" in topics:
        unknown.remove("rent_paid")
    if unknown:
        topics.append("deductions")

    if p.amount("sec_80d_parents") > PARENT_CAP_WITHOUT_SENIOR and p.parents_senior.status != "value":
        topics.append("parents_age")
    return topics, []


def questions_for(topics: list[str], conflicts: list[str]) -> list[str]:
    detail = ", ".join(conflicts) or "see above"
    return [QUESTIONS[t].format(detail=detail) for t in topics]


def to_tax_input(p: Profile, fy: str) -> dict:
    """Only call when clarify_topics returned no topics."""
    gross = p.gross_salary.value
    hra = p.amount("hra_received")
    basic = p.amount("basic_da") if hra else gross
    return {
        "fy": fy,
        "age": AGE_FOR_BAND[p.age_band.value],
        "basic_da": basic,
        "hra_received": hra,
        "other_salary": gross - basic - hra,
        "rent_paid": p.amount("rent_paid"),
        "metro": bool(p.metro.value),
        "sec_80c": p.amount("sec_80c"),
        "sec_80ccd1b": p.amount("sec_80ccd1b"),
        "sec_80d_self": p.amount("sec_80d_self"),
        "sec_80d_parents": p.amount("sec_80d_parents"),
        "parents_senior": bool(p.parents_senior.value),
        "home_loan_interest": p.amount("home_loan_interest"),
    }
