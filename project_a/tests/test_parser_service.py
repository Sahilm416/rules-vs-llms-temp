"""Money parsing, clarification policy, the service path without an LLM, and the compiled-code guard."""
import pytest

from project_a import service
from project_a.check_official import _matches
from project_a.impl_compiled.compiler import check_safe
from project_a.parser import rule_parser
from project_a.parser.money import find_amounts, parse_annual
from project_a.parser.policy import Profile, Slot, clarify_topics, to_tax_input


@pytest.mark.parametrize(
    "text,rupees",
    [("18 LPA", 1800000), ("1,50,000", 150000), ("1.5L", 150000), ("Rs 25k", 25000), ("2.1 Cr", 21000000), ("dedh lakh", 150000), ("40 hazaar", 40000), ("₹2,40,000", 240000)],
)
def test_money_units(text, rupees):
    assert find_amounts(text)[0].rupees == rupees


def test_monthly_wording_is_annualised():
    assert parse_annual("20,000 a month") == 240000
    assert parse_annual("15 hazaar mahina") == 180000


def test_small_bare_numbers_are_not_money():
    assert find_amounts("I am 34 and claim 80") == []


def _complete_profile() -> Profile:
    p = Profile()
    p.gross_salary = Slot("value", 1000000)
    p.age_band = Slot("value", "below_60")
    for name in ("rent_paid", "hra_received", "sec_80c", "sec_80ccd1b", "sec_80d_self", "sec_80d_parents", "home_loan_interest"):
        setattr(p, name, Slot("none", 0))
    return p


def test_complete_profile_asks_nothing():
    assert clarify_topics(_complete_profile()) == ([], [])


@pytest.mark.parametrize(
    "field,slot,topic",
    [
        ("gross_salary", Slot(), "salary"),
        ("age_band", Slot(), "age"),
        ("sec_80c", Slot(), "deductions"),
        ("sec_80c", Slot("conflict"), "conflict"),
        ("rent_paid", Slot("value", 240000), "hra_details"),
    ],
)
def test_gaps_force_a_question(field, slot, topic):
    p = _complete_profile()
    setattr(p, field, slot)
    if topic == "hra_details":
        p.hra_received = Slot()  # paying rent with HRA status unknown
    assert topic in clarify_topics(p)[0]


def test_parents_age_only_asked_when_it_changes_the_cap():
    p = _complete_profile()
    p.sec_80d_parents = Slot("value", 25000)
    assert clarify_topics(p)[0] == []
    p.sec_80d_parents = Slot("value", 25001)
    assert clarify_topics(p)[0] == ["parents_age"]


def test_unsupported_income_stops_everything():
    p = _complete_profile()
    p.unsupported = True
    assert clarify_topics(p)[0] == ["unsupported"]


def test_tax_input_splits_salary_when_hra_is_present():
    p = _complete_profile()
    p.hra_received, p.rent_paid = Slot("value", 200000), Slot("value", 240000)
    p.basic_da, p.metro = Slot("value", 500000), Slot("value", True)
    inp = to_tax_input(p, "2024-25")
    assert (inp["basic_da"], inp["hra_received"], inp["other_salary"], inp["metro"]) == (500000, 200000, 300000, True)


def test_service_answers_with_trace_and_reason():
    out = service.answer("age 26 | gross 7.75L/yr | no deductions", "2024-25", use_llm=False)
    assert out["status"] == "ok"
    assert (out["new"]["tax_payable"], out["recommended"]) == (0, "new")
    assert out["new"]["trace"] and "new regime" in out["why"]


def test_service_uses_the_year_requested():
    out = service.answer("age 26 | gross 12,75,000/yr | no deductions", "2025-26", use_llm=False)
    assert out["new"]["tax_payable"] == 0


def test_service_asks_instead_of_guessing():
    out = service.answer("tax on 30L?", "2024-25", use_llm=False)
    assert out["status"] == "need_info" and {"age", "deductions"} <= set(out["topics"])


def test_followup_answers_complete_the_request():
    first = service.answer("I'm 30. Gross salary 12 LPA.", "2024-25", use_llm=False)
    assert first["topics"] == ["deductions"]
    second = service.answer("I'm 30. Gross salary 12 LPA.", "2024-25", ("No deductions.",), use_llm=False)
    assert second["status"] == "ok"


def test_rule_parser_flags_out_of_scope():
    assert rule_parser.parse("gross 10 LPA and freelancing income").unsupported


@pytest.mark.parametrize(
    "code",
    ["import os", "from subprocess import run", "open('x')", "eval('1')", "x = ().__class__", "__import__('os')"],
)
def test_ast_guard_blocks_unsafe_code(code):
    assert check_safe(code)


def test_ast_guard_allows_exact_arithmetic():
    assert check_safe("from decimal import Decimal\nfrom math import floor\ndef compute(i):\n    return Decimal(1)") == []


def test_official_match_accepts_either_rounding_but_not_a_real_gap():
    assert _matches(13000, 13000, 13002.08)
    assert _matches(13002, 13000, 13002.08)
    assert not _matches(13100, 13000, 13002.08)
