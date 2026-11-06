"""Gemini client with a replayable on-disk cache.

Every response is stored in llm_cache/ together with its tokens and the latency measured
when it was really called. Re-running the evaluation replays those records, so the one-command
run reproduces all LLM numbers without a key and without spending quota. A cache miss with no key
raises CacheMiss, and evaluators report the gap rather than inventing a result.

`attempt` is part of the cache key: the determinism test uses attempts 0-9 to force real repeat calls.
"""
from __future__ import annotations

import hashlib
import json
import random
import threading
import time
from dataclasses import dataclass

import requests

from common.config import LLM_CACHE_DIR, gemini_api_key

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# USD per 1M tokens, Standard paid tier. Free-tier calls cost $0; these are what the same calls would
# cost once past the free tier. Source: https://aistudio.google.com/docs/pricing (read 2026-11-06).
PRICES = {
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
}

_lock = threading.Lock()
_last_call: dict[str, float] = {}
MIN_INTERVAL_S = {}  # model -> seconds between calls; set by callers from the measured free-tier limits
DEFAULT_INTERVAL_S = 6.5


class CacheMiss(RuntimeError):
    """Response not recorded and no API key available."""


class QuotaExhausted(RuntimeError):
    """The free tier's daily quota has run out."""


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int  # visible output plus thinking, both billed as output
    latency_s: float
    model: str
    cached: bool

    @property
    def cost_usd(self) -> float:
        rate_in, rate_out = PRICES[self.model]
        return (self.input_tokens * rate_in + self.output_tokens * rate_out) / 1_000_000


def _cache_path(key: str):
    return LLM_CACHE_DIR / key[:2] / f"{key}.json"


def cache_key(model: str, prompt: str, system: str | None, schema: dict | None, attempt: int) -> str:
    blob = json.dumps(
        {"model": model, "prompt": prompt, "system": system, "schema": schema, "attempt": attempt},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def _throttle(model: str) -> None:
    interval = MIN_INTERVAL_S.get(model, DEFAULT_INTERVAL_S)
    with _lock:
        wait = _last_call.get(model, 0.0) + interval - time.monotonic()
        _last_call[model] = max(time.monotonic(), _last_call.get(model, 0.0) + interval)
    if wait > 0:
        time.sleep(wait)


def _retry_delay(error: dict) -> float | None:
    for detail in error.get("details", []):
        if str(detail.get("@type", "")).endswith("RetryInfo"):
            return float(str(detail.get("retryDelay", "0s")).rstrip("s") or 0)
    return None


def _is_daily_quota(error: dict) -> bool:
    for detail in error.get("details", []):
        for violation in detail.get("violations", []) or []:
            if "PerDay" in str(violation.get("quotaId", "")):
                return True
    return False


def generate(
    prompt: str,
    *,
    model: str,
    system: str | None = None,
    schema: dict | None = None,
    attempt: int = 0,
    tag: str = "",
) -> LLMResponse:
    key = cache_key(model, prompt, system, schema, attempt)
    path = _cache_path(key)
    if path.exists():
        rec = json.loads(path.read_text())
        return LLMResponse(rec["text"], rec["input_tokens"], rec["output_tokens"], rec["latency_s"], model, True)

    api_key = gemini_api_key()
    if not api_key:
        raise CacheMiss(f"no recorded response for tag={tag!r} and GEMINI_API_KEY is not set")

    body: dict = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if schema:
        body["generationConfig"]["responseMimeType"] = "application/json"
        body["generationConfig"]["responseSchema"] = schema

    backoff = 5.0
    for _ in range(8):
        _throttle(model)
        started = time.perf_counter()
        try:
            resp = requests.post(
                API.format(model=model), headers={"x-goog-api-key": api_key}, json=body, timeout=300
            )
        except requests.RequestException:
            time.sleep(backoff)
            backoff = min(backoff * 2, 120)
            continue
        latency = time.perf_counter() - started
        if resp.status_code == 200:
            data = resp.json()
            candidates = data.get("candidates") or [{}]
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            usage = data.get("usageMetadata", {})
            rec = {
                "tag": tag,
                "model": model,
                "attempt": attempt,
                "text": text,
                "finish_reason": candidates[0].get("finishReason"),
                "input_tokens": usage.get("promptTokenCount", 0),
                "output_tokens": usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0),
                "latency_s": round(latency, 3),
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
            return LLMResponse(text, rec["input_tokens"], rec["output_tokens"], rec["latency_s"], model, False)
        if resp.status_code == 429:
            error = resp.json().get("error", {})
            if _is_daily_quota(error):
                raise QuotaExhausted(f"{model}: {error.get('message', '')[:200]}")
            time.sleep(max(_retry_delay(error) or backoff, 1.0) + random.uniform(0, 1))
            backoff = min(backoff * 2, 120)
            continue
        if resp.status_code in (500, 502, 503, 504):
            time.sleep(backoff)
            backoff = min(backoff * 2, 120)
            continue
        raise RuntimeError(f"Gemini HTTP {resp.status_code}: {resp.text[:300]}")
    raise RuntimeError(f"Gemini call failed after retries (tag={tag!r})")


def parse_json(text: str):
    """Parse a JSON reply, tolerating a markdown fence."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(cleaned)
