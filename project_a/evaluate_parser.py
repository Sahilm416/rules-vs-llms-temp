"""Score the three parser designs against the gold descriptions. Replays recorded LLM calls only."""
from __future__ import annotations

import json
import statistics
import time

from common.config import RESULTS_DIR
from common.llm import CacheMiss, QuotaExhausted
from project_a.parser import llm_parser, rule_parser
from project_a.parser.policy import Profile, clarify_topics
from project_a.tests.descriptions import DESCRIPTIONS

COMPARED = ("gross_salary", "age_band", "basic_da", "hra_received", "rent_paid", "metro", "sec_80c", "sec_80ccd1b", "sec_80d_self", "sec_80d_parents", "parents_senior", "home_loan_interest")


def _value(p: Profile, name: str):
    slot = getattr(p, name)
    if name in ("hra_received", "rent_paid", "sec_80c", "sec_80ccd1b", "sec_80d_self", "sec_80d_parents", "home_loan_interest"):
        return slot.value if slot.status == "value" else 0
    return slot.value if slot.status == "value" else None


def fields_match(p: Profile, gold: dict) -> list[str]:
    """Fields that differ from gold. basic_da, metro and parents_senior only matter where gold states them."""
    wrong = []
    for name in COMPARED:
        expected = gold[name]
        if name in ("basic_da", "metro", "parents_senior") and expected is None:
            continue
        if _value(p, name) != expected:
            wrong.append(name)
    return wrong


def score_one(kind: str, gold: dict | None, expected: list[str], profile: Profile, topics: list[str]) -> dict:
    if kind == "complete":
        wrong = fields_match(profile, gold)
        return {
            "correct": not topics and not wrong,
            "over_asked": bool(topics),
            "wrong_silently": not topics and bool(wrong),
            "guessed": False,
            "wrong_fields": wrong,
            "topics": topics,
        }
    return {
        "correct": set(expected) <= set(topics),
        "over_asked": False,
        "wrong_silently": False,
        "guessed": not topics,  # computed an answer when it had to ask
        "wrong_fields": [],
        "topics": topics,
    }


def summarize(rows: list[dict]) -> dict:
    complete = [r for r in rows if r["kind"] == "complete"]
    must_ask = [r for r in rows if r["kind"] != "complete"]
    return {
        "n": len(rows),
        "correct": sum(r["correct"] for r in rows),
        "complete_n": len(complete),
        "complete_correct": sum(r["correct"] for r in complete),
        "over_asked": sum(r["over_asked"] for r in complete),
        "wrong_silently": sum(r["wrong_silently"] for r in complete),
        "must_ask_n": len(must_ask),
        "must_ask_right_question": sum(r["correct"] for r in must_ask),
        "guessed": sum(r["guessed"] for r in must_ask),
    }


def evaluate(descriptions=DESCRIPTIONS) -> dict:
    designs = {"rule": [], "llm_only": [], "hybrid": [], "hybrid_union": []}
    latencies, costs = [], []
    missing = 0
    rule_seconds = 0.0
    for did, style, kind, text, gold, expected in descriptions:
        started = time.perf_counter()
        rp = rule_parser.parse(text)
        topics, _ = clarify_topics(rp)
        rule_seconds += time.perf_counter() - started
        designs["rule"].append({"id": did, "style": style, "kind": kind, **score_one(kind, gold, expected, rp, topics)})
        try:
            resp = llm_parser.call(text)
        except (CacheMiss, QuotaExhausted):
            missing += 1
            continue
        latencies.append(resp.latency_s)
        costs.append(resp.cost_usd)
        lp, ltopics = llm_parser.llm_only(text)
        designs["llm_only"].append({"id": did, "style": style, "kind": kind, **score_one(kind, gold, expected, lp, ltopics)})
        hp = llm_parser.hybrid(text)
        htopics, _ = clarify_topics(hp)
        designs["hybrid"].append({"id": did, "style": style, "kind": kind, **score_one(kind, gold, expected, hp, htopics)})
        # Designed after seeing the failures above, so its score is in-sample and flagged as such in reports.
        union = htopics + [t for t in topics if t not in htopics]
        designs["hybrid_union"].append({"id": did, "style": style, "kind": kind, **score_one(kind, gold, expected, hp, union)})
    out = {name: {"summary": summarize(rows), "rows": rows} for name, rows in designs.items()}
    out["rule"]["latency_ms_mean"] = 1000 * rule_seconds / len(descriptions)
    out["llm"] = {
        "missing_calls": missing,
        "latency_s_mean": statistics.mean(latencies) if latencies else None,
        "cost_per_1000_usd": 1000 * statistics.mean(costs) if costs else None,
    }
    return out


def main() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "a_parser.json").write_text(json.dumps(evaluate(), indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    result = evaluate()
    main()
    for name in ("rule", "llm_only", "hybrid", "hybrid_union"):
        print(name, result[name]["summary"])
        for row in result[name]["rows"]:
            if not row["correct"]:
                print("  ", row["id"], row["kind"], "topics=", row["topics"], "wrong=", row["wrong_fields"])
    print(result["llm"])
