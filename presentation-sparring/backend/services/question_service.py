"""질문 생성과 중복 판정 서비스."""

import logging
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Dict, List

from fastapi import HTTPException

import llm_client
import material_context
import prompts
from core.prompt_rules import SOURCE_TERM_PRESERVATION
from personas import (
    get_allowed_question_types,
    get_field_hint,
    get_model_hint,
    get_persona,
    get_question_policy_prompt,
)
from schemas import (
    QuestionRequest,
    QuestionResponse,
    QuestionType,
    SpeechTermAlias,
)

logger = logging.getLogger(__name__)

_QUESTION_TYPE_ALIASES: Dict[str, QuestionType] = {
    "evidence": "evidence",
    "근거 요구형": "evidence",
    "근거": "evidence",
    "counterexample": "counterexample",
    "반례 제시형": "counterexample",
    "반례": "counterexample",
    "application": "application",
    "확장 적용형": "application",
    "확장": "application",
    "definition": "definition",
    "정의 확인형": "definition",
    "정의": "definition",
}


def _parse_question_type(raw, fallback: str) -> QuestionType:
    """LLM이 반환한 질문 유형을 네 가지 내부 ID 중 하나로 정규화합니다."""
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        parsed = _QUESTION_TYPE_ALIASES.get(normalized)

        if parsed:
            return parsed

    fallback_parsed = _QUESTION_TYPE_ALIASES.get(fallback)

    if fallback_parsed:
        return fallback_parsed

    return "definition"


def _parse_int_list(raw, *, valid_values: set[int], limit: int = 3) -> List[int]:
    """LLM 배열 응답에서 유효한 슬라이드 번호만 순서대로 남깁니다."""
    if not isinstance(raw, list):
        return []

    result: List[int] = []

    for item in raw:
        if isinstance(item, str) and item.strip().isdigit():
            item = int(item.strip())

        if not isinstance(item, int) or item not in valid_values or item in result:
            continue

        result.append(item)

        if len(result) >= limit:
            break

    return sorted(result)


def _parse_string_list(raw, *, limit: int = 3) -> List[str]:
    """LLM 배열 응답에서 비어 있지 않은 문자열만 제한 개수만큼 남깁니다."""
    if not isinstance(raw, list):
        return []

    result: List[str] = []

    for item in raw:
        if not isinstance(item, str):
            continue

        normalized = item.strip()
        if not normalized or normalized in result:
            continue

        result.append(normalized[:240])

        if len(result) >= limit:
            break

    return result


def _normalize_source_text(value: str) -> str:
    """원문 포함 여부 비교를 위한 유니코드·공백 정규화."""
    return re.sub(
        r"\s+",
        " ",
        unicodedata.normalize("NFKC", value),
    ).strip().casefold()


def _find_source_term(source_text: str, candidate: str) -> str | None:
    """더 긴 영문 단어의 부분 문자열을 제외하고 원문의 실제 표기를 반환합니다."""
    normalized_source = unicodedata.normalize("NFKC", source_text)
    normalized_candidate = re.sub(
        r"\s+",
        " ",
        unicodedata.normalize("NFKC", candidate),
    ).strip()
    if not normalized_candidate:
        return None

    candidate_pattern = re.escape(normalized_candidate).replace(
        r"\ ",
        r"\s+",
    )
    matched = re.search(
        rf"(?<![A-Za-z0-9+#./-]){candidate_pattern}(?![A-Za-z0-9+#./-])",
        normalized_source,
        flags=re.IGNORECASE,
    )
    if not matched:
        return None

    return re.sub(r"\s+", " ", matched.group(0)).strip()


def _parse_speech_term_aliases(
    raw,
    *,
    source_text: str,
    term_limit: int = 8,
    alias_limit: int = 3,
) -> List[SpeechTermAlias]:
    """LLM 발음 후보 중 자료 원문에 근거하고 충돌하지 않는 항목만 남깁니다."""
    if not isinstance(raw, list):
        return []

    parsed: Dict[str, dict] = {}

    for item in raw:
        if not isinstance(item, dict):
            continue

        canonical_raw = item.get("canonical")
        if not isinstance(canonical_raw, str):
            continue

        canonical_candidate = re.sub(r"\s+", " ", canonical_raw).strip()
        canonical = _find_source_term(source_text, canonical_candidate)
        if canonical is None:
            continue
        canonical_key = _normalize_source_text(canonical)
        if (
            len(canonical) > 120
            or not re.search(r"[A-Za-z]", canonical)
            or not canonical_key
        ):
            continue

        aliases_raw = item.get("aliases")
        if not isinstance(aliases_raw, list):
            continue

        aliases: List[str] = []
        for alias_raw in aliases_raw:
            if not isinstance(alias_raw, str):
                continue

            alias = re.sub(r"\s+", " ", alias_raw).strip()
            compact_alias = alias.replace(" ", "")
            if (
                len(alias) > 80
                or len(compact_alias) < 2
                or not re.fullmatch(r"[가-힣 ]+", alias)
                # 필러는 버리는 값이 아니라 STT 원문에 남겨야 하는 값입니다.
                # 여기서는 기술 용어로 덮어쓰는 잘못된 별칭만 차단합니다.
                or re.fullmatch(r"(?:어+|음+|으+음+)", compact_alias)
                or alias in aliases
            ):
                continue

            aliases.append(alias)
            if len(aliases) >= alias_limit:
                break

        if not aliases:
            continue

        existing = parsed.get(canonical_key)
        if existing:
            for alias in aliases:
                if (
                    alias not in existing["aliases"]
                    and len(existing["aliases"]) < alias_limit
                ):
                    existing["aliases"].append(alias)
            continue

        parsed[canonical_key] = {
            "canonical": canonical,
            "aliases": aliases,
        }
        if len(parsed) >= term_limit:
            break

    alias_owners: Dict[str, set[str]] = {}
    for canonical_key, entry in parsed.items():
        for alias in entry["aliases"]:
            alias_key = _normalize_source_text(alias)
            alias_owners.setdefault(alias_key, set()).add(canonical_key)

    result: List[SpeechTermAlias] = []
    for canonical_key, entry in parsed.items():
        safe_aliases = [
            alias
            for alias in entry["aliases"]
            if alias_owners.get(_normalize_source_text(alias))
            == {canonical_key}
        ]
        if not safe_aliases:
            continue
        result.append(
            SpeechTermAlias(
                canonical=entry["canonical"],
                aliases=safe_aliases,
            )
        )

    return result


_TYPE_TRANSITIONS: Dict[QuestionType, QuestionType] = {
    "definition": "application",
    "evidence": "counterexample",
    "application": "definition",
    "counterexample": "evidence",
}


def _allowed_followup_types(
    current_type: QuestionType,
    difficulty: str,
    turn: int,
) -> set[QuestionType]:
    """프롬프트가 허용 범위를 벗어난 유형을 반환해도 API에서 한 번 더 제한합니다."""
    allowed = {current_type}

    # 유형 전환은 첫 번째 꼬리질문에서만 허용합니다.
    if turn > 0:
        return allowed

    if difficulty == "easy":
        if current_type == "definition":
            allowed.add("application")
        return allowed

    allowed.add(_TYPE_TRANSITIONS[current_type])
    return allowed


_QUESTION_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9가-힣]{2,}")
_QUESTION_STOPWORDS = {
    "무엇인가요",
    "설명해",
    "주세요",
    "말씀해",
    "어떻게",
    "이유는",
    "근거는",
    "관련",
    "대해서",
    "자료",
    "발표",
}

# 난이도는 질문의 깊이를 정하는 값이며, 이미 물은 질문을 다시 묻지 않는 기준과는 분리한다.
_QUESTION_DUPLICATE_THRESHOLD = 0.66


def _normalize_question_text(question: str) -> str:
    """질문 중복 비교용 문자열 정규화."""
    normalized = re.sub(r"\s+", " ", question or "").strip().lower()
    return re.sub(r"[^a-z0-9가-힣]", "", normalized)


def _question_tokens(question: str) -> set[str]:
    """질문 중복 비교용 핵심 토큰 추출."""
    return {
        token.lower()
        for token in _QUESTION_TOKEN_PATTERN.findall(question or "")
        if token.lower() not in _QUESTION_STOPWORDS
    }


def _question_similarity(left: str, right: str) -> float:
    """문자열 형태와 핵심 토큰을 함께 사용한 질문 유사도 계산."""
    left_normalized = _normalize_question_text(left)
    right_normalized = _normalize_question_text(right)
    if not left_normalized or not right_normalized:
        return 0.0
    if left_normalized == right_normalized:
        return 1.0

    character_score = SequenceMatcher(
        None,
        left_normalized,
        right_normalized,
    ).ratio()
    left_tokens = _question_tokens(left)
    right_tokens = _question_tokens(right)
    token_score = 0.0
    if left_tokens and right_tokens:
        token_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)

    return max(character_score, token_score)


def _is_duplicate_question(
    candidate: str,
    previous_questions: List[str],
    *,
    threshold: float = 0.72,
) -> bool:
    """이전 질문과 동일하거나 지나치게 유사한 질문 판정."""
    return any(
        _question_similarity(candidate, previous) >= threshold
        for previous in previous_questions
        if previous.strip()
    )


def _maximum_question_similarity(
    candidate: str,
    previous_questions: List[str],
) -> float:
    """이전 질문 중 가장 높은 유사도 조회."""
    similarities = [
        _question_similarity(candidate, previous)
        for previous in previous_questions
        if previous.strip()
    ]
    return max(similarities, default=0.0)


def _generate_question_data(
    req: QuestionRequest,
    *,
    persona_system: str,
    question_type_priority: List[str],
) -> dict:
    """중복 질문을 재생성하되 유효 후보가 있으면 흐름을 중단하지 않음."""
    prompt_slides = material_context.build_prompt_slides(
        req.script,
        req.slides,
    )
    prompt_script = material_context.compact_script(
        req.script
    )
    historical_questions = [
        question.strip()
        for question in req.excluded_questions
        if isinstance(question, str) and question.strip()
    ]

    # 프롬프트에는 탈락 초안도 보여 주되, 실제 중복 판정은
    # 사용자가 이미 받은 질문과만 비교하여 과도한 연쇄 탈락 방지
    prompt_blocked_questions = list(historical_questions)
    rejected_target_slides: set[int] = set()

    for attempt in range(4):
        system, user = prompts.build_question_prompt(
            persona_system=persona_system,
            script=prompt_script,
            slides=prompt_slides,
            difficulty=req.difficulty,
            question_type_priority=question_type_priority,
            excluded_questions=prompt_blocked_questions,
        )

        if attempt > 0:
            rejected_slide_text = (
                ", ".join(
                    str(index)
                    for index in sorted(rejected_target_slides)
                )
                or "없음"
            )
            user += (
                "\n\n[중복 질문 재생성 지시]\n"
                "직전에 생성한 질문은 이전 질문과 지나치게 유사했습니다. "
                "같은 개념의 정의·장점·작동 방식을 표현만 바꾸어 묻지 마세요. "
                "다른 핵심 개념, 다른 절차 단계, 다른 비교 지점 또는 "
                "다른 자료 구간을 선택하세요. "
                f"직전 탈락 후보가 사용한 슬라이드: {rejected_slide_text}. "
                "가능하면 해당 슬라이드를 피하고 자료 전체에서 새 질문을 고르세요."
            )

        try:
            data = llm_client.chat_json(
                system,
                user,
                get_model_hint(req.persona_id),
                kind="question",
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "LLM call failed in /api/questions"
            )
            raise HTTPException(
                status_code=502,
                detail=(
                    "AI 질문 생성 중 오류가 발생했습니다. "
                    "잠시 후 다시 시도해주세요."
                ),
            )

        candidate = str(data.get("question", "")).strip()
        if not candidate:
            continue

        similarity = _maximum_question_similarity(
            candidate,
            historical_questions,
        )
        target_slide = data.get("targets_slide")
        if (
            isinstance(target_slide, str)
            and target_slide.strip().isdigit()
        ):
            target_slide = int(target_slide.strip())
        if isinstance(target_slide, int):
            rejected_target_slides.add(target_slide)

        if similarity < _QUESTION_DUPLICATE_THRESHOLD:
            return data

        # 다음 재생성 프롬프트에만 탈락 초안 추가
        prompt_blocked_questions.append(candidate)

    raise HTTPException(
        status_code=502,
        detail=(
            "AI가 유효한 새 질문을 생성하지 못했습니다. "
            "같은 평가자로 다시 시작하거나 질문 횟수를 줄여주세요."
        ),
    )


def generate_question(req: QuestionRequest) -> QuestionResponse:
    persona = get_persona(req.persona_id)
    persona_system = (
        persona["system"]
        + get_field_hint(req.field)
        + get_question_policy_prompt(
            req.persona_id,
            req.difficulty,
        )
        + SOURCE_TERM_PRESERVATION
    )
    question_type_priority = list(
        get_allowed_question_types(
            req.persona_id,
            req.difficulty,
        )
    )
    data = _generate_question_data(
        req,
        persona_system=persona_system,
        question_type_priority=question_type_priority,
    )

    valid_slide_indices = {slide.index for slide in req.slides}
    targets = data.get("targets_slide")

    if isinstance(targets, str) and targets.strip().isdigit():
        targets = int(targets)

    if not isinstance(targets, int) or targets not in valid_slide_indices:
        targets = None

    # LLM 응답 누락 시 페르소나의 첫 번째 우선 유형 적용
    allowed_question_types = get_allowed_question_types(
        req.persona_id,
        req.difficulty,
    )
    question_type = _parse_question_type(
        data.get("question_type"),
        question_type_priority[0],
    )
    if question_type not in allowed_question_types:
        question_type = allowed_question_types[0]

    context_slides = _parse_int_list(
        data.get("context_slides"),
        valid_values=valid_slide_indices,
    )

    if targets is not None and targets not in context_slides:
        context_slides = sorted([targets, *context_slides])[:3]

    expected_answer_points = _parse_string_list(
        data.get("expected_answer_points"),
    )

    question = str(data.get("question", "")).strip()
    if not question:
        raise HTTPException(
            status_code=502,
            detail="AI가 유효한 질문을 생성하지 못했습니다. 잠시 후 다시 시도해주세요.",
        )

    question_focus = str(data.get("question_focus", "")).strip()
    context_source = "\n".join(
        [
            question,
            *[
                slide.text
                for slide in req.slides
                if slide.index in context_slides
            ],
        ]
    )
    speech_term_aliases = _parse_speech_term_aliases(
        data.get("speech_term_aliases"),
        source_text=context_source,
    )

    return QuestionResponse(
        question=question,
        question_type=question_type,
        targets_slide=targets,
        question_focus=question_focus or question[:160],
        context_slides=context_slides,
        expected_answer_points=expected_answer_points,
        speech_term_aliases=speech_term_aliases,
    )

