"""Implementation (c): an LLM compiles the rule text to Python once. A person reviews it; it then runs with no LLM.

raw/ holds the model's output byte for byte. reviewed/ holds what ships. The difference between them is
the review, recorded in REVIEW_LOG.md. Compiled code passes an AST allow-list before it is ever imported.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
from pathlib import Path

from common.llm import generate
from project_a.trace import rule_text

HERE = Path(__file__).parent
MODEL = "gemini-3.6-flash"
ALLOWED_IMPORTS = {"decimal", "fractions", "math"}
BANNED_NAMES = {"eval", "exec", "open", "compile", "__import__", "globals", "locals", "getattr", "setattr", "input"}

SYSTEM = "You are a careful compiler that turns legal tax rules into exact, deterministic Python code."

PROMPT = """Convert the rule text below into one self-contained Python 3.10 module.

Requirements:
- Define `def compute(inp: dict) -> dict`.
- Import only from: decimal, fractions, math. No file, network or other I/O. No other imports.
- Use exact arithmetic (Decimal or Fraction), never binary floats, for money calculations.
- `inp` has these keys: fy (str), age (int), basic_da (int, basic salary + dearness allowance), hra_received (int),
  other_salary (int), rent_paid (int, annual), metro (bool, residence in Delhi, Mumbai, Kolkata or Chennai),
  sec_80c (int), sec_80ccd1b (int), sec_80d_self (int), sec_80d_parents (int), parents_senior (bool),
  home_loan_interest (int). All money is whole rupees per year.
- Raise ValueError if inp["fy"] is not the financial year this rule text covers.
- Return {{"old": R, "new": R, "recommended": "old" or "new"}} where R is a dict with:
  total_income (int), slab_tax (float), rebate (float), surcharge (float, after marginal relief), cess (float),
  total_before_rounding (float), tax_payable (int), and trace (list).
- Each trace row is {{"group": "income" or "tax", "clause": <clause ID from the rule text without brackets>,
  "description": str, "amount": float}}. Income rows must sum to total_income, and tax rows must sum to tax_payable.
  Deductions, rebates and reliefs are negative amounts. Include rounding rows for [S288A] and [S288B].
- Output only the Python code, with no markdown fence and no commentary.

RULE TEXT:
{rules}
"""


def compile_rules(fy: str, model: str = MODEL) -> Path:
    """Call the LLM once and store its output unchanged, recording which model produced it."""
    response = generate(PROMPT.format(rules=rule_text(fy)), model=model, system=SYSTEM, tag=f"compile-{fy}")
    code = response.text.strip()
    if code.startswith("```"):
        code = code.split("\n", 1)[1].rsplit("```", 1)[0]
    path = HERE / "raw" / f"fy{fy.replace('-', '_')}.py"
    path.parent.mkdir(exist_ok=True)
    path.write_text(code + "\n")
    models_path = path.parent / "MODELS.json"
    models = json.loads(models_path.read_text()) if models_path.exists() else {}
    models[fy] = {"model": model, "latency_s": response.latency_s, "input_tokens": response.input_tokens, "output_tokens": response.output_tokens, "cost_usd": response.cost_usd}
    models_path.write_text(json.dumps(models, indent=1) + "\n")
    return path


def check_safe(code: str) -> list[str]:
    """Reject anything outside the allow-list before the module is imported."""
    problems = []
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                    problems.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                problems.append(f"from {node.module} import")
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            problems.append(f"name {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            problems.append(f"dunder attribute {node.attr}")
    return problems


def load(stage: str, fy: str):
    """Load the compiled module from raw/ or reviewed/ after the safety check."""
    path = HERE / stage / f"fy{fy.replace('-', '_')}.py"
    if not path.exists():
        raise FileNotFoundError(f"no {stage} compiled rules for FY {fy}")
    problems = check_safe(path.read_text())
    if problems:
        raise ValueError(f"{path.name} failed the safety check: {problems}")
    spec = importlib.util.spec_from_file_location(f"compiled_{stage}_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("fy")
    parser.add_argument("--model", default=MODEL)
    args = parser.parse_args()
    print(compile_rules(args.fy, args.model))
