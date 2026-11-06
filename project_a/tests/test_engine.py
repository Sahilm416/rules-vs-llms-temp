"""Hand-coded engine against the hand-worked golden cases, the frozen suite, and the trace checker."""
import json
from pathlib import Path

import pytest

from project_a.impl_rules import engine
from project_a.tests.golden import GOLDEN, _inp
from project_a.tests.oracle import compute as oracle
from project_a.trace import check_answer, rule_text

CASES_DIR = Path(__file__).parent / "cases"
FIELDS = ("total_income", "slab_tax", "rebate", "surcharge", "cess", "total_before_rounding", "tax_payable")
SUPPORTED = [p.stem[2:].replace("_", "-") for p in (Path(engine.__file__).parent).glob("fy*.toml")]


def _cases():
    for fy in SUPPORTED:
        yield from json.loads((CASES_DIR / f"fy{fy.replace('-', '_')}.json").read_text())


@pytest.mark.parametrize("name,inp,old,new", GOLDEN, ids=[g[0] for g in GOLDEN])
def test_oracle_matches_hand_worked(name, inp, old, new):
    result = oracle(inp)
    assert (result["old"]["tax_payable"], result["new"]["tax_payable"]) == (old, new)


@pytest.mark.parametrize("name,inp,old,new", [g for g in GOLDEN if g[1]["fy"] in SUPPORTED], ids=lambda v: v if isinstance(v, str) else "")
def test_engine_matches_hand_worked(name, inp, old, new):
    result = engine.compute(inp)
    assert (result["old"]["tax_payable"], result["new"]["tax_payable"]) == (old, new)


@pytest.mark.parametrize("case", list(_cases()), ids=lambda c: c["id"])
def test_engine_matches_suite_every_field(case):
    result = engine.compute(case["input"])
    assert result["recommended"] == case["expected"]["recommended"]
    for regime in ("old", "new"):
        for field in FIELDS:
            assert result[regime][field] == pytest.approx(case["expected"][regime][field], abs=0.011), (regime, field)


@pytest.mark.parametrize("case", list(_cases()), ids=lambda c: c["id"])
def test_every_rupee_traces_to_a_clause(case):
    assert check_answer(engine.compute(case["input"]), case["input"]["fy"]) == []


def test_unknown_year_is_loud_not_silent():
    with pytest.raises(engine.UnsupportedYear):
        engine.compute(_inp(fy="2099-00", gross=1000000))


def test_rule_text_exists_for_supported_years():
    for fy in SUPPORTED:
        assert "[S288B]" in rule_text(fy)
