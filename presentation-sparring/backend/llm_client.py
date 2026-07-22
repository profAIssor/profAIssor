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
from typing import Literal, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


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

RequestKind = Literal[
    "question",
    "evaluate",
    "retry",
    "followup",
    "unknown_closure",
    "report",
    "reference_repair",
    "chat",
]

# 연결 재사용과 일시 오류 재시도 설정
_RETRY_POLICY = Retry(
    total=2,
    connect=2,
    read=0,
    status=2,
    backoff_factor=0.6,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"POST"}),
    respect_retry_after_header=True,
    raise_on_status=False,
)
_SESSION = requests.Session()
_SESSION.mount(
    "https://",
    HTTPAdapter(
        max_retries=_RETRY_POLICY,
        pool_connections=10,
        pool_maxsize=10,
    ),
)

# 호출 목적별 출력 토큰 상한.
# question/evaluate는 응답 JSON 스키마가 고정이라 짧게 제한하고,
# report는 슬라이드 커버리지 배열이 슬라이드 수에 비례해 길어지므로 여유를 둔다.
# 출력 상한은 비용 통제와 '잘린 JSON → 파싱 실패' 방지를 겸한다.
_MAX_OUTPUT_TOKENS = {
    "question": 700,
    "evaluate": 900,
    "retry": 700,
    "followup": 700,
    "unknown_closure": 900,
    "report": 4096,
    "reference_repair": 1800,
    "chat": 1200,
}


def _sampling_config(request_kind: RequestKind) -> tuple[float, int]:
    """호출 목적별 (temperature, max_output_tokens)를 반환.

    평가는 같은 답변에 같은 판정이 나와야 하므로 온도를 낮추고(0.3),
    질문 생성과 리포트는 표현이 매번 똑같이 반복되지 않도록 0.7을 유지한다.
    """
    temperature = (
        0.3
        if request_kind
        in {
            "evaluate",
            "unknown_closure",
            "reference_repair",
        }
        else 0.7
    )
    max_tokens = _MAX_OUTPUT_TOKENS.get(request_kind, _MAX_OUTPUT_TOKENS["chat"])
    return temperature, max_tokens

# 로컬·배포 환경에서 필요에 따라 토큰 로그를 끌 수 있게
_USAGE_LOG_ENABLED = os.getenv(
    "LLM_USAGE_LOG",
    "true",
).lower() in {"1", "true", "yes", "on"}




def _log_usage(
    *,
    provider: str,
    model: str,
    request_kind: RequestKind,
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


def _call_openai(
    system: str,
    user: str,
    model: str,
    request_kind: RequestKind,
) -> str:
    """OpenAI를 호출하고 응답 텍스트와 사용량을 처리"""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    started_at = time.perf_counter()

    temperature, max_tokens = _sampling_config(request_kind)

    response = _SESSION.post(
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
            # 평가 0.3 / 질문·리포트 0.7 — 판정 일관성과 질문 다양성을 분리
            "temperature": temperature,

            # 잘린 JSON 파싱 실패와 비용 폭주를 동시에 방지
            "max_tokens": max_tokens,

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
        request_kind=request_kind,
        input_tokens=int(usage.get("prompt_tokens", 0)),
        output_tokens=int(usage.get("completion_tokens", 0)),
        total_tokens=int(usage.get("total_tokens", 0)),
        elapsed_ms=elapsed_ms,
    )

    return data["choices"][0]["message"]["content"]


def _call_gemini(
    system: str,
    user: str,
    model: str,
    request_kind: RequestKind,
) -> str:
    """Gemini generateContent API를 호출하고 응답 텍스트를 반환"""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    url = (
        f"{_MODEL_CONFIG['gemini']['url']}/"
        f"{model}:generateContent?key={api_key}"
    )

    temperature, max_tokens = _sampling_config(request_kind)

    response = _SESSION.post(
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
                "temperature": temperature,
                # 고정 1024는 슬라이드가 많은 리포트에서 JSON이 잘릴 수 있어
                # 호출 목적별 상한으로 교체
                "maxOutputTokens": max_tokens,
                # OpenAI의 response_format과 같은 목적: JSON 외 텍스트 차단
                "responseMimeType": "application/json",
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


def _is_mock_answer_sufficient(user: str) -> bool:
    """기대 답변 요소의 핵심 토큰이 답변에 충분히 등장하면 충분한 답변으로 판정.

    실제 LLM의 '답변이 질문의 명시적 요구를 모두 충족하면 followup=null' 흐름을
    API 키 없이도 검증할 수 있게 하는 결정론적 근사
    -> 각 기대 요소에서 2글자 이상 토큰을 뽑아, 모든 요소가 답변에서 충분히 발견되면 충분으로 봄
    """
    answer = _extract_section(user, "학생 답변")
    expected = _extract_section(user, "기대 답변 요소")

    points = [
        line.lstrip("- ").strip()
        for line in expected.splitlines()
        if line.strip().startswith("-")
    ]

    if not points or not answer:
        return False

    for point in points:
        tokens = re.findall(r"[A-Za-z0-9가-힣]{2,}", point)
        if not tokens:
            continue
        # '개념', '기준' 같은 흔한 토큰 하나만으로 충분 판정이 나지 않도록,
        # 토큰이 2개 이상인 요소는 최소 2개가 답변에 등장해야 일치로 본다.
        matched = sum(1 for token in tokens if token in answer)
        if matched < min(2, len(tokens)):
            return False

    return True


def _mock_followup(user: str) -> tuple[Optional[str], Optional[str]]:
    """설정 횟수까지 꼬리질문 생성 및 첫 꼬리질문의 인접 유형 전환."""
    turn_match = re.search(r"turn=(\d+)", user)
    turn = int(turn_match.group(1)) if turn_match else 0

    # 서버 하드가드와 별개로 mock 자체도 남은 횟수를 존중한다.
    max_turns_match = re.search(r"max_turns=(\d+)", user)
    max_turns = int(max_turns_match.group(1)) if max_turns_match else 3

    if turn >= max_turns:
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


def _mock_report_revisions(user: str) -> list[dict]:
    """슬라이드와 질의응답 기록에서 결정론적으로 1~2개의 수정 제안을 만듦

    API 키 없이도 프론트가 revisions 렌더링을 검증할 수 있게 하는 목적이며,
    실제 LLM 판단을 흉내 내기보다 스키마와 흐름을 재현하는 데 집중
    """
    slide_section = _extract_section(user, "슬라이드")
    slide_matches = re.findall(r"\[슬라이드\s+(\d+)\]\s*(.*)", slide_section)

    revisions: list[dict] = []

    if slide_matches:
        index, text = slide_matches[0]
        revisions.append(
            {
                "slide_index": int(index),
                "observation": (
                    f"슬라이드 {index}의 핵심 문구 '{_shorten(text, limit=40)}'가 "
                    "대본에서 풀어서 설명되지 않고 그대로 낭독되었습니다."
                ),
                "impact": "배경지식이 없는 청중은 해당 개념의 의미를 놓칠 수 있습니다.",
                "action_type": "term_explanation",
                "action": "핵심 용어가 처음 등장할 때 쉬운 말로 한 번 풀어서 설명하세요.",
                "example": f"'{_shorten(text, limit=30)}'은 쉽게 말하면 ~라는 의미입니다.",
            }
        )

    transcript_section = _extract_section(user, "질의응답")
    gap_match = re.search(r"부족:\s*([^\n]+)", transcript_section)
    if gap_match and gap_match.group(1).strip() not in ("", "없음"):
        revisions.append(
            {
                "slide_index": None,
                "observation": f"질의응답에서 '{_shorten(gap_match.group(1))}' 지점이 부족하다고 평가되었습니다.",
                "impact": "질문의 핵심을 짚었더라도 근거 없이는 설득력이 떨어질 수 있습니다.",
                "action_type": "signal_phrase",
                "action": "답변을 결론부터 말한 뒤 근거를 덧붙이는 순서로 재구성하세요.",
                "example": "결론부터 말씀드리면 ~입니다. 그 이유는 ~이기 때문입니다.",
            }
        )

    return revisions


def _mock_answer_structure_tip(user: str) -> str:
    transcript_section = _extract_section(user, "질의응답")
    if "부족:" in transcript_section and "없음" not in transcript_section.split("부족:")[1][:10]:
        return (
            "질문을 받으면 먼저 결론을 한 문장으로 말한 뒤 근거를 붙이고, "
            "마지막에 한계나 예외를 짧게 덧붙이는 순서를 연습하세요. "
            "지금은 근거 제시가 결론보다 늦게 나오는 경우가 있었습니다."
        )
    return (
        "질문을 받으면 결론→근거→한계 순서로 답하는 습관을 유지하세요. "
        "특히 압박 질문에서는 결론을 먼저 말해야 청중이 흐름을 놓치지 않습니다."
    )


_MOCK_UNKNOWN_NUANCE = re.compile(
    r"모르겠|모릅니다|기억(?:이\s*)?(?:안\s*나|나지\s*않)|"
    r"준비(?:를|가)?\s*(?:못|안)\s*(?:했|됐|되)|"
    r"공부(?:를|가)?\s*(?:못|안)\s*(?:했|해)|"
    r"배운\s*적(?:이)?\s*없|넘어가\s*주|패스|스킵|pass|skip"
)


def _mock_is_nuanced_unknown(answer: str) -> bool:
    """서버 정규식을 통과한 뉘앙스형 답변 불가를 실제 LLM처럼 재분류

    답변 불가 표현이 있고 그 외 실질적 내용이 거의 없으면 unknown으로 봄
    불확실 표현 뒤에 실제 설명이 이어지는 경우는 answered를 유지
    """
    normalized = re.sub(r"\s+", " ", answer.strip())
    if not normalized:
        return False
    if not _MOCK_UNKNOWN_NUANCE.search(normalized):
        return False
    # 답변 불가 표현을 제거한 나머지가 짧으면 실질 내용이 없다고 판단
    stripped = _MOCK_UNKNOWN_NUANCE.sub("", normalized)
    stripped = re.sub(r"[\s,.!?…]|그|음|어|아|좀|잘|그냥|사실|솔직히", "", stripped)
    return len(stripped) < 20


def _mock_unknown_retry(user: str) -> tuple[str, str]:
    """답변 불가 뒤 동일 주제를 한 단계 낮춘 mock 재질문 생성."""
    focus = _shorten(
        _extract_section(user, "질문 초점"),
        limit=55,
    )

    return (
        f"힌트를 바탕으로, {focus}에서 가장 기본이 되는 의미나 관계 한 가지만 "
        "말씀해 주실 수 있나요?",
        "definition",
    )


def _call_mock(
    system: str,
    user: str,
    model: str,
    request_kind: RequestKind,
) -> str:
    """API 키 없이 전체 흐름을 검사할 수 있는 JSON 응답을 반환"""
    _ = model, request_kind

    if '"targets_slide"' in system:
        return json.dumps(_mock_question(system, user), ensure_ascii=False)

    if '"verdict"' in system and '"followup"' in system:
        answer_status = _extract_section(user, "답변 상태 사전 판정")

        # 서버가 answered로 사전 판정했더라도, 뉘앙스형 답변 불가라면
        # 실제 LLM처럼 unknown으로 재분류(프롬프트의 재분류 규칙 재현)
        if answer_status != "unknown":
            student_answer = _extract_section(user, "학생 답변")
            if _mock_is_nuanced_unknown(student_answer):
                answer_status = "unknown"

        if answer_status == "unknown":
            slide_section = _extract_section(user, "질문 관련 슬라이드")
            related_slides = [
                int(index)
                for index in re.findall(r"\[슬라이드\s+(\d+)\]", slide_section)[:2]
            ]
            retry_question, retry_question_type = _mock_unknown_retry(user)
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
                    "followup": retry_question,
                    "followup_question_type": retry_question_type,
                    "rubric": {},
                },
                ensure_ascii=False,
            )

        followup, followup_question_type = _mock_followup(user)

        # 충분 판정 유지 및 남은 설정 횟수만큼의 꼬리질문 진행
        if _is_mock_answer_sufficient(user):
            return json.dumps(
                {
                    "answer_status": "answered",
                    "verdict": "충분",
                    "strengths": "질문이 요구한 핵심 요소를 모두 답변에 포함했습니다.",
                    "gaps": "없음",
                    "supplement": None,
                    "related_slides": [],
                    "followup": followup,
                    "followup_question_type": followup_question_type,
                    "rubric": {
                        "직접성": "우수",
                        "근거": "보통",
                        "논리": "보통",
                    },
                },
                ensure_ascii=False,
            )

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
            "revisions": _mock_report_revisions(user),
            "answer_structure_tip": _mock_answer_structure_tip(user),
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
    *,
    kind: RequestKind = "chat",
) -> str:
    """설정된 provider에 요청을 보내고 원문 텍스트를 반환"""
    provider_call = _DISPATCH.get(PROVIDER)
    if provider_call is None:
        raise RuntimeError(
            f"Unknown LLM_PROVIDER={PROVIDER!r}. "
            "Use openai|gemini|mock."
        )

    model = _resolve_model(PROVIDER, model_hint)
    return provider_call(
        system,
        user,
        model,
        kind,
    )


def chat_json(
    system: str,
    user: str,
    model_hint: Optional[str] = None,
    *,
    kind: RequestKind = "chat",
) -> dict:
    """LLM 응답의 JSON 객체 변환"""
    raw_response = chat(
        system,
        user,
        model_hint,
        kind=kind,
    )

    try:
        return extract_json(raw_response)
    except (json.JSONDecodeError, ValueError):
        # 프롬프트·응답 원문을 기록하지 않는 파싱 실패 로그
        _logger.exception(
            "LLM JSON parsing failed: kind=%s response_chars=%d",
            kind,
            len(raw_response),
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