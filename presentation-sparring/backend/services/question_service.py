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
from personas import (
    build_persona_system,
    get_allowed_question_types,
    get_model_hint,
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
    "what",
    "how",
    "why",
    "could",
    "would",
    "please",
    "explain",
    "describe",
    "presentation",
    "the",
    "and",
    "from",
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


_INDIRECT_QUESTION_PREAMBLE_PATTERN = re.compile(
    r"(?:라고|다고|이라고)\s*"
    r"(?:하셨는데|말씀하셨는데|설명하셨는데|언급하셨는데)"
    r"|발표(?:에서|에서는|중에?)?.{0,90}"
    r"(?:말씀|설명|언급)하셨(?:는데|습니다만)"
    r"|\b(?:you\s+(?:mentioned|said|stated|explained)).{0,100}"
    r"\b(?:what\s+do\s+you\s+think|do\s+you\s+think)\b",
    re.IGNORECASE,
)


def _has_indirect_question_preamble(question: str) -> bool:
    """자료 인용 서두 뒤에 실제 요구를 붙인 장황한 질문인지 판정."""
    normalized = re.sub(r"\s+", " ", question).strip()
    return bool(
        _INDIRECT_QUESTION_PREAMBLE_PATTERN.search(normalized)
    )


def _question_misses_difficulty_depth(
    question: str,
    difficulty: str,
    language: str,
) -> bool:
    """어려움 질문이 정의·명칭 확인 수준으로 낮아졌는지 판정."""
    if difficulty != "hard":
        return False

    normalized = re.sub(r"\s+", " ", question).strip().lower()
    if language == "en":
        depth_pattern = re.compile(
            r"\b(?:condition|limitation|failure|exception|assumption|"
            r"trade-?off|impact|effect|cause|why|how|under\s+what|"
            r"what\s+happens\s+if)\b",
            re.IGNORECASE,
        )
    else:
        depth_pattern = re.compile(
            r"(?:조건|한계|실패|예외|전제|가정|통제|환경|상황|"
            r"성립|깨지|달라지|비용|부하|성능|이유|원인|영향|인과|왜|어떻게|"
            r"trade-?off)"
        )
    return not bool(depth_pattern.search(normalized))


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
        # 전체 대본은 별도 블록으로 전달하므로 슬라이드마다 같은 대본
        # 구간을 다시 붙이지 않습니다.
        include_script_segments=False,
    )
    prompt_script = material_context.compact_script(
        req.script
    )
    historical_questions = [
        question.strip()
        for question in req.excluded_questions[-12:]
        if isinstance(question, str) and question.strip()
    ]

    # 프롬프트에는 탈락 초안도 보여 주되, 실제 중복 판정은
    # 사용자가 이미 받은 질문과만 비교하여 과도한 연쇄 탈락 방지
    prompt_blocked_questions = list(historical_questions)
    rejected_target_slides: set[int] = set()
    last_rejection_reason = ""
    last_rejected_candidate = ""
    last_non_duplicate_candidate: dict | None = None

    for attempt in range(4):
        system, user = prompts.build_question_prompt(
            persona_system=persona_system,
            script=prompt_script,
            slides=prompt_slides,
            difficulty=req.difficulty,
            question_type_priority=question_type_priority,
            excluded_questions=prompt_blocked_questions,
            conversation_summary=req.conversation_summary,
            language=req.language,
        )

        if attempt > 0 and last_rejection_reason == "duplicate":
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
        elif attempt > 0 and last_rejection_reason == "style":
            user += (
                "\n\n[질문 문장 재작성 지시]\n"
                "직전 초안은 발표 내용을 되받는 서두 때문에 장황했습니다. "
                "핵심 대상이나 조건부터 바로 시작하고, 학생이 답해야 할 이유·작동 방식·"
                "판단 기준·조건을 한 문장으로 직접 물으세요. "
                "'~라고 하셨는데', '~라고 설명하셨는데', '~라고 언급하셨는데', "
                "'어떻게 생각하나요?'를 사용하지 마세요. "
                f"직전 초안: {last_rejected_candidate[:500]}"
            )
        elif attempt > 0 and last_rejection_reason == "difficulty":
            user += (
                "\n\n[어려움 난이도 재작성 지시]\n"
                "직전 초안은 명칭·역할·단순 차이 확인에 머물러 어려움 난이도에 "
                "미치지 못했습니다. 같은 핵심 주제를 유지하되 자료에 근거한 조건, "
                "한계, 실패 상황, 전제, 원인과 영향 중 하나를 골라 깊게 물으세요. "
                "여러 요구를 합치지 말고 학생이 이유나 인과관계를 설명하게 하세요. "
                f"직전 초안: {last_rejected_candidate[:500]}"
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
        misses_difficulty_depth = _question_misses_difficulty_depth(
            candidate,
            req.difficulty,
            req.language,
        )
        if (
            similarity < _QUESTION_DUPLICATE_THRESHOLD
            and not _has_indirect_question_preamble(candidate)
            and not misses_difficulty_depth
        ):
            return data

        if similarity < _QUESTION_DUPLICATE_THRESHOLD:
            # 문장 스타일이나 리터럴 깊이 게이트만 통과하지 못한 후보는
            # 네 번 모두 재생성에 실패했을 때 사용할 안전 후보로 보존합니다.
            # 중복 후보는 이 경로에 절대 들어오지 않습니다.
            last_non_duplicate_candidate = data

        last_rejected_candidate = candidate
        if _has_indirect_question_preamble(candidate):
            last_rejection_reason = "style"
            continue
        if misses_difficulty_depth:
            last_rejection_reason = "difficulty"
            continue

        last_rejection_reason = "duplicate"
        target_slide = data.get("targets_slide")
        if (
            isinstance(target_slide, str)
            and target_slide.strip().isdigit()
        ):
            target_slide = int(target_slide.strip())
        if isinstance(target_slide, int):
            rejected_target_slides.add(target_slide)

        # 중복 후보만 다음 프롬프트의 제외 목록에 추가한다.
        prompt_blocked_questions.append(candidate)

    if last_non_duplicate_candidate is not None:
        logger.warning(
            "Question validation exhausted; using the last non-duplicate "
            "candidate (persona=%s difficulty=%s reason=%s)",
            req.persona_id,
            req.difficulty,
            last_rejection_reason,
        )
        return last_non_duplicate_candidate

    raise HTTPException(
        status_code=502,
        detail=(
            "AI가 유효한 새 질문을 생성하지 못했습니다. "
            "같은 평가자로 다시 시작하거나 질문 횟수를 줄여주세요."
        ),
    )


def generate_question(req: QuestionRequest) -> QuestionResponse:
    persona_system = build_persona_system(
        req.persona_id,
        req.field,
        req.language,
        req.difficulty,
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
    speech_term_aliases = (
        []
        if req.language == "en"
        else _parse_speech_term_aliases(
            data.get("speech_term_aliases"),
            source_text=context_source,
        )
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

