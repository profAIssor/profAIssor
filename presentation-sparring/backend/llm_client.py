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
            "temperature": 0.3,

            # JSON 객체 출력 강제
            "response_format": {"type": "json_object"},
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


_MOCK_QUESTION_TYPES = {
    "evidence",
    "counterexample",
    "application",
    "definition",
}


def _mock_question_type(system: str) -> str:
    """프롬프트의 persona 우선순위에서 mock 질문 유형을 결정"""
    priority_match = re.search(
        r"\[질문 유형 우선순위\]\s*\n([^\n]+)",
        system,
    )

    if priority_match:
        candidates = [
            item.strip()
            for item in priority_match.group(1).split(">")
        ]

        for candidate in candidates:
            if candidate in _MOCK_QUESTION_TYPES:
                # 쉬움에서는 명시적인 예외 자료를 판정하기 어려우므로
                # mock 반례 질문 대신 확장 적용형으로 낮춤
                if (
                    candidate == "counterexample"
                    and "[난이도: 쉬움]" in system
                ):
                    return "application"

                return candidate

    return "definition"


def _mock_question(system: str, user: str) -> dict:
    """persona 우선순위와 전체 슬라이드 흐름을 반영한 mock 질문을 생성"""
    question_type = _mock_question_type(system)

    slide_matches = re.findall(
        r"\[슬라이드\s+(\d+)\]\s*(.*?)(?=\n\[슬라이드\s+\d+\]|\n\n\[제외할 이전 질문\]|\Z)",
        user,
        re.DOTALL,
    )

    excluded_section = _extract_section(user, "제외할 이전 질문")
    excluded_count = len(
        [line for line in excluded_section.splitlines() if line.strip().startswith("-")]
    )

    if slide_matches:
        offset = excluded_count % len(slide_matches)
        slide_matches = slide_matches[offset:] + slide_matches[:offset]

    context_slides = [
        int(index)
        for index, _ in slide_matches[:3]
    ]

    if slide_matches:
        representative_index = int(slide_matches[0][0])
        first_text = _shorten(slide_matches[0][1], limit=55)
        second_text = (
            _shorten(slide_matches[1][1], limit=45)
            if len(slide_matches) > 1
            else f"아직 묻지 않은 핵심 요소 {excluded_count + 1}"
        )
        subject = f"{first_text}와 {second_text}의 연결"
    else:
        representative_index = None
        subject = "발표의 핵심 내용과 전체 흐름"

    templates = {
        "definition": (
            f"자료 전체 흐름을 기준으로 {subject}에서 가장 중요한 개념 차이를 "
            "설명해 주실 수 있나요?"
        ),
        "evidence": (
            f"자료 전체 흐름에서 {subject}을 뒷받침하는 가장 직접적인 근거 하나는 무엇인가요?"
        ),
        "counterexample": (
            f"자료에 제시된 조건을 기준으로 {subject}이 성립하지 않을 수 있는 "
            "예외 한 가지는 무엇인가요?"
        ),
        "application": (
            f"자료에서 설명한 {subject}을 관련 예시에 적용하면 어떻게 판단할 수 있나요?"
        ),
    }

    return {
        "question": templates[question_type],
        "question_type": question_type,
        "targets_slide": representative_index,
        "question_focus": subject,
        "context_slides": context_slides,
        "expected_answer_points": [
            first_text if slide_matches else "발표의 핵심 내용",
            second_text if slide_matches else "핵심 내용 사이의 관계",
        ],
    }


def _mock_followup(user: str) -> tuple[Optional[str], Optional[str]]:
    """중복을 피하고 첫 꼬리질문에서만 인접 유형으로 전환"""
    turn_match = re.search(r"turn=(\d+)", user)
    turn = int(turn_match.group(1)) if turn_match else 0

    if turn >= 3:
        return None, None

    question_type = _extract_section(user, "현재 질문 유형")
    if not question_type:
        question_type = _extract_section(user, "질문 유형")

    answer_excerpt = _shorten(
        _extract_section(user, "학생 답변"),
    )
    focus = _shorten(
        _extract_section(user, "질문 초점"),
        limit=55,
    )

    if turn == 0 and question_type == "definition":
        return (
            f"{focus}과 관련된 자료 속 예시 하나를 골라 방금 설명한 기준을 "
            "어떻게 적용하는지 말씀해 주실 수 있나요?",
            "application",
        )

    templates = {
        "definition": (
            f"방금 '{answer_excerpt}'라고 설명했는데, {focus}을 구분하는 핵심 기준 하나를 "
            "더 명확히 말씀해 주실 수 있나요?"
        ),
        "evidence": (
            f"방금 '{answer_excerpt}'라고 답했는데, 그 근거가 {focus}을 뒷받침한다고 "
            "볼 수 있는 이유는 무엇인가요?"
        ),
        "counterexample": (
            f"방금 '{answer_excerpt}'라고 설명했는데, 그 예외 조건에서 {focus}은 "
            "어떻게 달라지나요?"
        ),
        "application": (
            f"방금 '{answer_excerpt}'라고 답했는데, 같은 기준을 자료의 다른 예시에 "
            "적용하면 어떻게 판단할 수 있나요?"
        ),
    }

    return templates.get(question_type, templates["definition"]), question_type or "definition"


def _call_mock(system: str, user: str, model: str) -> str:
    """API 키 없이 전체 흐름을 검사할 수 있는 JSON 응답을 반환"""
    _ = model

    if '"targets_slide"' in system:
        return json.dumps(_mock_question(system, user), ensure_ascii=False)

    if '"verdict"' in system and '"followup"' in system:
        answer_status = _extract_section(user, "답변 상태 사전 판정")

        if answer_status == "unknown":
            slide_section = _extract_section(user, "질문 관련 슬라이드")
            related_slides = [
                int(index)
                for index in re.findall(r"\[슬라이드\s+(\d+)\]", slide_section)[:2]
            ]
            return json.dumps(
                {
                    "answer_status": "unknown",
                    "verdict": "확인 필요",
                    "strengths": "",
                    "gaps": "질문의 핵심 내용을 발표 전에 다시 확인해 보세요.",
                    "supplement": (
                        "질문과 관련된 핵심 개념과 비교 기준을 자료에서 다시 확인해 보세요. "
                        "정의만 외우기보다 두 개념의 목적과 적용 대상을 구분해 정리하는 것이 좋습니다."
                    ),
                    "related_slides": related_slides,
                    "followup": None,
                    "followup_question_type": None,
                    "rubric": {},
                },
                ensure_ascii=False,
            )

        followup, followup_question_type = _mock_followup(user)
        return json.dumps(
            {
                "answer_status": "answered",
                "verdict": "질문의 핵심에는 답했지만 자료 흐름과의 연결을 조금 더 설명할 수 있습니다.",
                "strengths": "질문에서 요구한 중심 개념을 벗어나지 않고 답했습니다.",
                "gaps": "관련 슬라이드의 기준이나 예시를 사용한 설명이 아직 충분하지 않습니다.",
                "supplement": None,
                "related_slides": [],
                "followup": followup,
                "followup_question_type": followup_question_type,
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
    """LLM 응답의 JSON 객체 변환"""

    raw_response = chat(system, user, model_hint)

    try:
        return extract_json(raw_response)
    except (json.JSONDecodeError, ValueError):
        # 민감 정보 제외를 위한 응답 앞부분 기록
        _logger.exception(
            "LLM JSON parsing failed: response=%r",
            raw_response[:1000],
        )
        raise


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