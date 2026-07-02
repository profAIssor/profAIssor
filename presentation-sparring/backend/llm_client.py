"""LLM provider abstraction.

Switch providers with the LLM_PROVIDER env var: gemini | groq | anthropic | mock.
A single `chat(system, user, model_hint)` entry point hides each provider behind
a thin REST wrapper. `mock` returns deterministic canned JSON so the whole app
can be demoed / curl-tested with no API keys.
"""
import json
import os
import re
from typing import Optional

import requests

PROVIDER = os.getenv("LLM_PROVIDER", "mock").lower()

# Per-provider default model, plus an optional "high tier" model used when a
# persona requests a heavier model (model_hint == "high"). Env-overridable.
_MODEL_CONFIG = {
    "anthropic": {
        "default": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5"),
        "high": os.getenv("ANTHROPIC_MODEL_HIGH", "claude-opus-4-8"),
        "url": "https://api.anthropic.com/v1/messages",
    },
    "gemini": {
        "default": os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
        "high": os.getenv("GEMINI_MODEL_HIGH", "gemini-2.0-flash"),
        "url": "https://generativelanguage.googleapis.com/v1beta/models",
    },
    "groq": {
        "default": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "high": os.getenv("GROQ_MODEL_HIGH", "llama-3.3-70b-versatile"),
        "url": "https://api.groq.com/openai/v1/chat/completions",
    },
}

_TIMEOUT = 60


def _resolve_model(provider: str, model_hint: Optional[str]) -> str:
    cfg = _MODEL_CONFIG.get(provider, {})
    if model_hint == "high":
        return cfg.get("high", cfg.get("default", ""))
    return cfg.get("default", "")


# --------------------------------------------------------------- providers
def _call_anthropic(system: str, user: str, model: str) -> str:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    resp = requests.post(
        _MODEL_CONFIG["anthropic"]["url"],
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(block.get("text", "") for block in data.get("content", []))


def _call_gemini(system: str, user: str, model: str) -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    url = f"{_MODEL_CONFIG['gemini']['url']}/{model}:generateContent?key={key}"
    resp = requests.post(
        url,
        headers={"content-type": "application/json"},
        json={
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1024},
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    parts = data["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts)


def _call_groq(system: str, user: str, model: str) -> str:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not set")
    resp = requests.post(
        _MODEL_CONFIG["groq"]["url"],
        headers={
            "Authorization": f"Bearer {key}",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.7,
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _call_mock(system: str, user: str, model: str) -> str:
    """Deterministic canned JSON keyed on which prompt shape called us.

    Lets the entire setup->spar->report flow run + be curl-tested offline.
    """
    if '"targets_slide"' in system:  # question generation
        return json.dumps({
            "question": "발표에서 제시한 핵심 주장의 근거가 명확하지 않은데, "
                        "그 주장을 뒷받침하는 구체적인 데이터나 사례가 있나요?",
            "targets_slide": 1,
        }, ensure_ascii=False)
    if '"verdict"' in system and '"followup"' in system:  # evaluate
        # Give a followup only on the very first turn to exercise the loop.
        followup = None
        if "현재 턴: 0" in user:
            followup = "방금 언급한 근거가 실제로 그 결론으로 이어지는지, 논리 단계를 하나씩 설명해 주시겠어요?"
        return json.dumps({
            "verdict": "질문에 부분적으로 답했으나 근거 제시가 부족합니다.",
            "strengths": "핵심 개념을 이해하고 답변의 방향은 맞습니다.",
            "gaps": "구체적 근거와 예시가 부족해 설득력이 약합니다.",
            "followup": followup,
        }, ensure_ascii=False)
    # report
    return json.dumps({
        "content_feedback": "핵심 주장은 있으나 근거의 구체성이 부족합니다. 데이터/사례로 보강하세요.",
        "delivery_feedback": "전달 구조는 무난하나 전문 용어에 대한 쉬운 설명이 필요합니다.",
        "response_feedback": "질문의 의도를 파악하는 능력은 좋으나, 압박 질문에서 근거로 방어하는 훈련이 필요합니다.",
        "slide_coverage": [],  # filled deterministically by the report route
    }, ensure_ascii=False)


_DISPATCH = {
    "anthropic": _call_anthropic,
    "gemini": _call_gemini,
    "groq": _call_groq,
    "mock": _call_mock,
}


# --------------------------------------------------------------- public API
def chat(system: str, user: str, model_hint: Optional[str] = None) -> str:
    """Send a system+user prompt to the configured provider, return raw text."""
    fn = _DISPATCH.get(PROVIDER)
    if fn is None:
        raise RuntimeError(
            f"Unknown LLM_PROVIDER={PROVIDER!r}. Use gemini|groq|anthropic|mock."
        )
    model = _resolve_model(PROVIDER, model_hint)
    return fn(system, user, model)


def chat_json(system: str, user: str, model_hint: Optional[str] = None) -> dict:
    """chat() + robust JSON extraction (strips code fences / surrounding prose)."""
    raw = chat(system, user, model_hint)
    return extract_json(raw)


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM response."""
    text = text.strip()
    # strip ```json ... ``` fences if present
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # fall back to the outermost {...}
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError(f"Could not parse JSON from LLM response: {text[:200]}")
