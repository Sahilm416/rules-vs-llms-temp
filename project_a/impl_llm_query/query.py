"""Implementation (b): for each request, an LLM reads the rule text and computes the answer itself."""
from __future__ import annotations

import json

from common.llm import LLMResponse, generate, parse_json
from project_a.trace import rule_text

MODEL = "gemini-3.6-flash"

SYSTEM = (
    "You are an Indian income-tax calculator. Apply only the rule text you are given, never your own "
    "memory of tax law. Work carefully and be exact to the rupee."
)

_REGIME = {
    "type": "OBJECT",
    "properties": {
        "total_income": {"type": "NUMBER"},
        "slab_tax": {"type": "NUMBER"},
        "rebate": {"type": "NUMBER"},
        "surcharge": {"type": "NUMBER"},
        "cess": {"type": "NUMBER"},
        "total_before_rounding": {"type": "NUMBER"},
        "tax_payable": {"type": "NUMBER"},
        "trace": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "group": {"type": "STRING", "enum": ["income", "tax"]},
                    "clause": {"type": "STRING"},
                    "description": {"type": "STRING"},
                    "amount": {"type": "NUMBER"},
                },
                "required": ["group", "clause", "description", "amount"],
            },
        },
    },
    "required": ["total_income", "slab_tax", "rebate", "surcharge", "cess", "total_before_rounding", "tax_payable", "trace"],
}

SCHEMA = {
    "type": "OBJECT",
    "properties": {"old": _REGIME, "new": _REGIME, "recommended": {"type": "STRING", "enum": ["old", "new"]}},
    "required": ["old", "new", "recommended"],
}

PROMPT = """Compute the income tax for this salaried person under both the old and the new regime, following the rule text exactly.

Trace rules: every row cites a clause ID from the rule text, without brackets. "income" rows must sum to total_income and
"tax" rows must sum to tax_payable. Deductions, rebates and reliefs are negative amounts. Include the [S288A] and [S288B] rounding rows.
"surcharge" is the amount after marginal relief. "rebate" is a positive number.

Input fields: basic_da = basic salary + dearness allowance; metro = residence in Delhi, Mumbai, Kolkata or Chennai.
All money is whole rupees per year.

RULE TEXT:
{rules}

INPUT:
{inp}
"""


def build_prompt(inp: dict, rules_fy: str | None = None) -> str:
    """`rules_fy` lets the Task 5 experiment give the model last year's rules on purpose."""
    return PROMPT.format(rules=rule_text(rules_fy or inp["fy"]), inp=json.dumps(inp, sort_keys=True))


def call(inp: dict, attempt: int = 0, rules_fy: str | None = None, model: str = MODEL) -> LLMResponse:
    return generate(
        build_prompt(inp, rules_fy),
        model=model,
        system=SYSTEM,
        schema=SCHEMA,
        attempt=attempt,
        tag=f"query-{inp['fy']}-rules{rules_fy or inp['fy']}",
    )


def compute(inp: dict, attempt: int = 0, rules_fy: str | None = None, model: str = MODEL) -> dict:
    return parse_json(call(inp, attempt, rules_fy, model).text)
