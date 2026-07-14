"""LLM provider abstraction.

LLM_PROVIDER 환경변수로 openai, gemini, mock 중 하나를 선택
각 provider는 하나의 모델 설정만 사용하며, persona별 모델 티어 라우팅은 사용하지 않음

주의 : 배포 시 로그 기록 없애기
"""

import json
import logging
import os
import re
import time
from typing import Optional

import requests


PROVIDER = os.getenv("LLM_PROVIDER", "mock").lower()

# provider별로 하나의 모델만 사용하며, persona는 프롬프트만 변경할 예정
_MODEL_CONFIG = {
    "openai": {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "url": "https://api.openai.com/v1/chat/completions",
    },
    "gemini": {
        "model": os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
        "url": "https://generativelanguage.googleapis.com/v1beta/models",
    },
    "mock": {
        "model": "mock",
    },
}

_TIMEOUT = 60
# Uvicorn 로그 형식을 그대로 사용
_logger = logging.getLogger("uvicorn.error")

# 로컬·배포 환경에서 필요에 따라 토큰 로그를 끌 수 있게
_USAGE_LOG_ENABLED = os.getenv(
    "LLM_USAGE_LOG",
    "true",
).lower() in {"1", "true", "yes", "on"}


def _detect_request_kind(system: str) -> str:
    """응답 JSON 스키마를 기준으로 LLM 호출 목적을 구분."""
    if '"targets_slide"' in system:
        return "question"

    if '"verdict"' in system and '"followup"' in system:
        return "evaluate"

    if '"slide_coverage"' in system:
        return "report"

    return "chat"


def _log_usage(
    *,
    provider: str,
    model: str,
    request_kind: str,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    elapsed_ms: int,
) -> None:
    """프롬프트 원문 없이 호출별 토큰과 응답 시간만 기록"""
    if not _USAGE_LOG_ENABLED:
        return

    _logger.info(
        "[LLM_USAGE] provider=%s model=%s kind=%s "
        "input=%d output=%d total=%d latency_ms=%d",
        provider,
        model,
        request_kind,
        input_tokens,
        output_tokens,
        total_tokens,
        elapsed_ms,
    )

def _resolve_model(provider: str, model_hint: Optional[str] = None) -> str:
    """선택한 provider의 단일 모델명을 반환

    model_hint는 기존 main.py 호출부와의 호환성을 위해 받지만,
    모델 선택에는 사용하지 않음
    """
    _ = model_hint
    return _MODEL_CONFIG.get(provider, {}).get("model", "")


def _call_openai(system: str, user: str, model: str) -> str:
    """OpenAI를 호출하고 응답 텍스트와 사용량을 처리"""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    started_at = time.perf_counter()

    response = requests.post(
        _MODEL_CONFIG["openai"]["url"],
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
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
    response.raise_for_status()

    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    data = response.json()
    usage = data.get("usage") or {}

    _log_usage(
        provider="openai",
        model=model,
        request_kind=_detect_request_kind(system),
        input_tokens=int(usage.get("prompt_tokens", 0)),
        output_tokens=int(usage.get("completion_tokens", 0)),
        total_tokens=int(usage.get("total_tokens", 0)),
        elapsed_ms=elapsed_ms,
    )

    return data["choices"][0]["message"]["content"]


def _call_gemini(system: str, user: str, model: str) -> str:
    """Gemini generateContent API를 호출하고 응답 텍스트를 반환"""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    url = (
        f"{_MODEL_CONFIG['gemini']['url']}/"
        f"{model}:generateContent?key={api_key}"
    )

    response = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        json={
            "system_instruction": {
                "parts": [{"text": system}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user}],
                }
            ],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 1024,
            },
        },
        timeout=_TIMEOUT,
    )
    response.raise_for_status()

    data = response.json()
    parts = data["candidates"][0]["content"]["parts"]
    return "".join(part.get("text", "") for part in parts)


def _extract_section(text: str, header: str) -> str:
    """Mock 응답에서 ``[헤더]`` 다음 구간을 추출"""
    pattern = rf"\[{re.escape(header)}\]\s*\n(.*?)(?=\n\n\[|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else ""


def _shorten(text: str, limit: int = 45) -> str:
    """Mock 질문에 넣을 입력 일부를 짧게 정리"""
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return "구체적인 설명이 부족하다"
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "…"


def _mock_question(user: str) -> dict:
    """첫 슬라이드의 번호와 내용을 포함한 mock 최초 질문을 생성"""
    slide_match = re.search(r"\[슬라이드\s+(\d+)\]\s*(.+)", user)
    if slide_match:
        slide_index = int(slide_match.group(1))
        slide_claim = _shorten(slide_match.group(2), limit=60)
        return {
            "question": (
                f"{slide_index}번 슬라이드에서 '{slide_claim}'라고 제시했는데, "
                "이 결론이 도출된 구체적인 조건과 핵심 근거는 무엇인가요?"
            ),
            "targets_slide": slide_index,
        }

    return {
        "question": (
            "발표에서 제시한 핵심 주장이 어떤 조건과 근거에서 도출됐는지 "
            "구체적으로 설명해 주실 수 있나요?"
        ),
        "targets_slide": None,
    }


def _mock_followup(user: str) -> Optional[str]:
    """turn 0~2에서 학생 답변 표현을 포함한 mock 꼬리질문을 반환"""
    turn_match = re.search(r"현재 턴:\s*(\d+)", user)
    turn = int(turn_match.group(1)) if turn_match else 0
    answer_excerpt = _shorten(_extract_section(user, "학생의 직전 답변"))

    if turn == 0:
        return (
            f"방금 '{answer_excerpt}'라고 답했는데, 그 판단을 뒷받침하는 "
            "구체적인 측정 기준이나 확인 과정은 무엇인가요?"
        )
    if turn == 1:
        return (
            f"방금 '{answer_excerpt}'라고 설명했는데, 그 과정이 성립하기 위해 "
            "반드시 필요한 전제 조건은 무엇인가요?"
        )
    if turn == 2:
        return (
            f"방금 '{answer_excerpt}'라고 했는데, 그 전제 조건이 깨지는 예외 상황에서도 "
            "같은 결과 해석이 유지된다고 볼 수 있나요?"
        )
    return None


def _call_mock(system: str, user: str, model: str) -> str:
    """API 키 없이 전체 흐름을 검사할 수 있는 JSON 응답을 반환"""
    _ = model

    if '"targets_slide"' in system:
        return json.dumps(_mock_question(user), ensure_ascii=False)

    if '"verdict"' in system and '"followup"' in system:
        return json.dumps(
            {
                "verdict": "질문의 방향에는 답했지만 근거와 과정 설명이 더 필요합니다.",
                "strengths": "핵심 개념을 이해하고 답변의 중심을 유지했습니다.",
                "gaps": "판단 기준, 전제 조건, 결과 해석을 뒷받침하는 설명이 부족합니다.",
                "followup": _mock_followup(user),
                "rubric": {
                    "직접성": "보통",
                    "근거": "부족",
                    "논리": "보통",
                },
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "content_feedback": (
                "핵심 주장은 있으나 근거의 구체성이 부족합니다. "
                "데이터나 사례로 보강하세요."
            ),
            "delivery_feedback": (
                "전달 구조는 무난하나 전문 용어에 대한 쉬운 설명이 필요합니다."
            ),
            "response_feedback": (
                "질문의 의도를 파악하는 능력은 좋으나, "
                "압박 질문에서 근거로 방어하는 훈련이 필요합니다."
            ),
            "slide_coverage": [],
        },
        ensure_ascii=False,
    )


_DISPATCH = {
    "openai": _call_openai,
    "gemini": _call_gemini,
    "mock": _call_mock,
}


def chat(
    system: str,
    user: str,
    model_hint: Optional[str] = None,
) -> str:
    """설정된 provider에 요청을 보내고 원문 텍스트를 반환"""
    provider_call = _DISPATCH.get(PROVIDER)
    if provider_call is None:
        raise RuntimeError(
            f"Unknown LLM_PROVIDER={PROVIDER!r}. "
            "Use openai|gemini|mock."
        )

    model = _resolve_model(PROVIDER, model_hint)
    return provider_call(system, user, model)


def chat_json(
    system: str,
    user: str,
    model_hint: Optional[str] = None,
) -> dict:
    """LLM 응답에서 JSON 객체를 추출해 반환"""
    raw_response = chat(system, user, model_hint)
    return extract_json(raw_response)


def extract_json(text: str) -> dict:
    """코드 블록이나 설명이 섞인 응답에서 첫 JSON 객체를 추출"""
    normalized = text.strip()

    # ```json ... ``` 형태의 코드 블록을 우선 제거
    fenced_json = re.search(
        r"```(?:json)?\s*(.*?)```",
        normalized,
        re.DOTALL,
    )
    if fenced_json:
        normalized = fenced_json.group(1).strip()

    try:
        return json.loads(normalized)
    except json.JSONDecodeError:
        pass

    # JSON 바깥에 설명이 붙은 경우 가장 바깥쪽 객체를 다시 시도
    json_object = re.search(r"\{.*\}", normalized, re.DOTALL)
    if json_object:
        return json.loads(json_object.group(0))

    raise ValueError(
        "Could not parse JSON from LLM response: "
        f"{normalized[:200]}"
    )