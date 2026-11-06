"""LLM extractor. The model finds the facts and quotes its evidence; code decides what the facts are worth.

Two outputs come from one call, so the comparison is fair:
- llm_only: trust the model's own rupee values and its own clarify_topics.
- hybrid: keep a value only if its quote really appears in the user's text, recompute rupees with money.py,
  and let the deterministic policy decide whether to ask.
"""
from __future__ import annotations

import json

from common.llm import LLMResponse, generate, parse_json
from project_a.parser.money import parse_annual
from project_a.parser.policy import MONEY_FIELDS, Profile, Slot

MODEL = "gemini-3.5-flash-lite"

SYSTEM = (
    "You extract facts from an Indian salaried taxpayer's description, which may be in English or Hinglish. "
    "Never guess. Only report what the text says. Never compute tax."
)

_FIELD = {
    "type": "OBJECT",
    "properties": {
        "status": {"type": "STRING", "enum": ["value", "none", "unknown", "conflict"]},
        "evidence": {"type": "STRING"},
        "rupees_per_year": {"type": "NUMBER"},
    },
    "required": ["status", "evidence"],
}

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "gross_salary": _FIELD,
        "age": {
            "type": "OBJECT",
            "properties": {
                "status": {"type": "STRING", "enum": ["value", "unknown", "conflict"]},
                "evidence": {"type": "STRING"},
                "age_band": {"type": "STRING", "enum": ["below_60", "60_to_79", "80_plus", "unknown"]},
            },
            "required": ["status", "evidence", "age_band"],
        },
        **{name: _FIELD for name in MONEY_FIELDS},
        "city": {"type": "STRING"},
        "parents_senior": {"type": "STRING", "enum": ["yes", "no", "unknown"]},
        "unsupported_income_or_status": {"type": "BOOLEAN"},
        "unsupported_evidence": {"type": "STRING"},
        "clarify_topics": {
            "type": "ARRAY",
            "items": {"type": "STRING", "enum": ["salary", "age", "hra_details", "deductions", "parents_age", "conflict", "unsupported"]},
        },
    },
    "required": ["gross_salary", "age", *MONEY_FIELDS, "city", "parents_senior", "unsupported_income_or_status", "unsupported_evidence", "clarify_topics"],
}

PROMPT = """Extract facts about the taxpayer from the description.

Field meanings. Each is the taxpayer's own annual figure:
gross_salary: gross salary before tax. basic_da: basic plus dearness allowance. hra_received: house rent allowance received.
rent_paid: rent the taxpayer pays. sec_80c: 80C investments (PPF, ELSS, PF, term insurance...). sec_80ccd1b: own NPS contribution.
sec_80d_self: health premium for self or family. sec_80d_parents: health premium for parents.
home_loan_interest: interest on a self-occupied home loan.

Status for each field:
- value: the text states an amount. "evidence" is the exact words from the text that contain the amount, copied verbatim, including any "per month" wording.
  "rupees_per_year" is that amount converted to rupees per year.
- none: the text explicitly rules it out, including a blanket statement such as "no deductions", "nothing else" or "baaki kuch nahi".
- unknown: not mentioned, or mentioned with no amount.
- conflict: the text says two incompatible things about it.

Special rules:
- In-hand pay, take-home pay, CTC, or a salary figure with no stated period and no "LPA" wording: gross_salary status is unknown.
- age: a "senior citizen" with no number has age_band unknown. Use the taxpayer's age only, not a parent's. If the description is
  about another named person (for example "Papa ki age 70"), that person is the taxpayer.
- city: the city of residence if stated, otherwise an empty string.
- parents_senior: yes if a parent is stated to be 60 or older, no if stated to be younger, otherwise unknown.
- unsupported_income_or_status: true if the text mentions capital gains, business or freelance income, rent received from a property, or non-resident status.

clarify_topics: the questions that must be asked before tax can be computed exactly.
salary = gross annual salary missing or unclear. age = age band unknown.
hra_details = rent or HRA mentioned but one of annual rent, annual HRA, basic plus DA, or city is missing.
deductions = a deductible item (80C, NPS, health insurance, parents' health insurance, home-loan interest, rent) is neither stated with an amount nor ruled out.
parents_age = parents' premium above 25000 with parents' age unknown.
conflict = the text contradicts itself. unsupported = unsupported income or status.
Use an empty list if nothing needs asking.

DESCRIPTION:
{text}
"""


def call(text: str, attempt: int = 0) -> LLMResponse:
    return generate(PROMPT.format(text=text), model=MODEL, system=SYSTEM, schema=SCHEMA, attempt=attempt, tag="parse")


def _build_profile(raw: dict) -> Profile:
    p = Profile()
    for name in ("gross_salary", *MONEY_FIELDS):
        field = raw.get(name) or {}
        value = field.get("rupees_per_year")
        setattr(p, name, Slot(field.get("status", "unknown"), int(value) if value else (0 if field.get("status") == "none" else None), field.get("evidence", "")))
    age = raw.get("age") or {}
    band = age.get("age_band")
    p.age_band = Slot(age.get("status", "unknown"), band if band != "unknown" else None, age.get("evidence", ""))
    if p.age_band.status == "value" and not p.age_band.value:
        p.age_band.status = "unknown"
    city = (raw.get("city") or "").strip().lower()
    if city:
        p.metro = Slot("value", city in {"delhi", "new delhi", "mumbai", "bombay", "kolkata", "calcutta", "chennai", "madras"}, city)
    if raw.get("parents_senior") in ("yes", "no"):
        p.parents_senior = Slot("value", raw["parents_senior"] == "yes", "")
    p.unsupported = bool(raw.get("unsupported_income_or_status"))
    p.unsupported_evidence = raw.get("unsupported_evidence", "")
    return p


def llm_only(text: str, attempt: int = 0) -> tuple[Profile, list[str]]:
    raw = parse_json(call(text, attempt).text)
    return _build_profile(raw), list(raw.get("clarify_topics") or [])


def hybrid(text: str, attempt: int = 0) -> Profile:
    """Verify evidence and recompute amounts in code. A quote not found in the text becomes unknown, which forces a question."""
    p = _build_profile(parse_json(call(text, attempt).text))
    lowered = " ".join(text.lower().split())
    for name in ("gross_salary", *MONEY_FIELDS):
        slot: Slot = getattr(p, name)
        if slot.status != "value":
            continue
        evidence = " ".join(slot.evidence.lower().split())
        if not evidence or evidence not in lowered:
            setattr(p, name, Slot("unknown", None, slot.evidence))
            continue
        recomputed = parse_annual(slot.evidence)
        if recomputed is not None:
            slot.value = recomputed
    return p


def debug_dump(text: str) -> str:
    return json.dumps(parse_json(call(text).text), indent=1, ensure_ascii=False)
