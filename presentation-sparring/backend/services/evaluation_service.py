"""답변 평가, 무응답 재질문, 후속 질문 서비스."""

import logging
import re
from typing import Dict, List, Optional

from fastapi import HTTPException

import llm_client
import material_context
import prompts
from core.prompt_rules import get_source_term_preservation
from personas import (
    get_allowed_question_types,
    get_field_hint,
    get_model_hint,
    get_persona,
    get_question_policy_prompt,
)
from schemas import (
    EvaluateRequest,
    EvaluateResponse,
    QuestionType,
    SpeechTermAlias,
)
from services.question_service import (
    _TYPE_TRANSITIONS,
    _QUESTION_TOKEN_PATTERN,
    _is_duplicate_question,
    _parse_int_list,
    _parse_question_type,
    _parse_speech_term_aliases,
    _parse_string_list,
    _question_tokens,
)

logger = logging.getLogger(__name__)

_RUBRIC_AXES = ("직접성", "근거", "논리")
_RUBRIC_VALUES = {"부족", "보통", "우수"}


def _parse_rubric(raw) -> Dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {
        axis: raw[axis]
        for axis in _RUBRIC_AXES
        if isinstance(raw.get(axis), str) and raw[axis] in _RUBRIC_VALUES
    }


def _parse_expected_point_assessments(
    raw,
    expected_answer_points: List[str],
    answer: str,
) -> Dict[int, bool]:
    """모델의 요소별 의미 판정을 검증해 후속 질문 선택에만 사용합니다."""
    if not isinstance(raw, list) or not expected_answer_points:
        return {}

    normalized_answer = re.sub(r"\s+", " ", answer).strip().casefold()
    parsed: Dict[int, bool] = {}
    conflicted_indices: set[int] = set()

    for item in raw:
        if not isinstance(item, dict):
            continue

        point_index = item.get("point_index")
        if isinstance(point_index, str) and point_index.strip().isdigit():
            point_index = int(point_index.strip())

        covered = item.get("covered")
        evidence = item.get("answer_evidence")
        if (
            isinstance(point_index, bool)
            or not isinstance(point_index, int)
            or point_index < 0
            or point_index >= len(expected_answer_points)
            or not isinstance(covered, bool)
            or not isinstance(evidence, str)
            or point_index in conflicted_indices
        ):
            continue

        normalized_evidence = re.sub(
            r"\s+",
            " ",
            evidence,
        ).strip().casefold()
        if covered and (
            not normalized_evidence
            or normalized_evidence not in normalized_answer
        ):
            # covered 판정은 학생 답변의 실제 원문 근거가 있을 때만 신뢰합니다.
            continue
        if not covered and normalized_evidence:
            # 미충족 요소는 근거를 비우도록 한 출력 계약과 모순되므로 신뢰하지 않습니다.
            continue

        if point_index in parsed and parsed[point_index] != covered:
            parsed.pop(point_index, None)
            conflicted_indices.add(point_index)
            continue

        parsed[point_index] = covered

    return parsed


def _rubric_counts(rubric: Dict[str, str]) -> Dict[str, int]:
    """평가 등급별 축 개수 집계."""
    return {
        value: sum(1 for result in rubric.values() if result == value)
        for value in _RUBRIC_VALUES
    }


def _should_ask_followup(
    req: EvaluateRequest,
    rubric: Dict[str, str],
    gaps: str,
) -> bool:
    """난이도와 평가 결과에 따른 꼬리질문 사용 판정."""
    if req.turn >= req.max_turns:
        return False

    if req.difficulty == "easy":
        return False

    counts = _rubric_counts(rubric)

    if req.difficulty == "medium":
        return counts.get("부족", 0) >= 2

    # 어려움의 한 차례 심화 질문 보장
    return True


def _next_action_after_current_question(req: EvaluateRequest) -> str:
    """현재 질문 슬롯 종료 뒤 다음 기본 질문 또는 전체 종료 결정."""
    return "move_to_new_root" if req.turn < req.max_turns else "finish"


def _fallback_supplement(
    question_focus: str,
    current_type: QuestionType,
    language: str = "ko",
) -> str:
    """모델 보충 설명 누락 시 사용할 사고 방향 안내."""
    focus = re.sub(r"\s+", " ", question_focus.strip())[:120]
    subject = focus or "현재 질문의 핵심 개념"
    if language == "en":
        english_subject = focus or "the key concept in this question"
        english_guides: Dict[QuestionType, str] = {
            "definition": "Start by identifying what role it plays and how it differs from a similar concept.",
            "evidence": "Find one fact, result, or relationship in the presentation that connects the cause to the conclusion.",
            "counterexample": "Consider which changed condition would make the result different.",
            "application": "First identify one decision criterion from the original explanation that can be applied here.",
        }
        return (
            f"This question asks you to explain {english_subject}. "
            f"{english_guides[current_type]}"
        )
    type_guides: Dict[QuestionType, str] = {
        "definition": (
            "익숙한 용어를 그대로 반복하기보다, 그 개념이 어떤 역할을 하고 "
            "비슷한 개념과 무엇이 다른지부터 떠올려 보세요."
        ),
        "evidence": (
            "결론을 먼저 외우기보다, 발표 자료에서 원인과 결과를 연결해 주는 "
            "사실이나 수치를 한 가지 찾아보세요."
        ),
        "counterexample": (
            "설명이 항상 성립한다고 가정하지 말고, 조건이 달라졌을 때 "
            "결과가 바뀌는 지점을 먼저 생각해 보세요."
        ),
        "application": (
            "새로운 상황의 정답을 바로 고르기보다, 원래 설명에서 사용할 수 있는 "
            "판단 기준 한 가지를 먼저 꺼내 보세요."
        ),
    }
    return f"이 질문은 {subject}을 한 번에 설명하도록 요구합니다. {type_guides[current_type]}"


def _fallback_unknown_retry(
    question_focus: str,
    current_type: QuestionType,
    language: str = "ko",
) -> tuple[str, str, List[str]]:
    """현재 질문의 사고 단계를 한 단계 낮춘 재질문 계약 생성."""
    focus = re.sub(r"\s+", " ", question_focus.strip())[:120]
    subject = focus or "현재 질문의 핵심 내용"
    if language == "en":
        english_subject = focus or "the key point of the question"
        english_templates: Dict[QuestionType, tuple[str, str, List[str]]] = {
            "definition": (
                f"Could you first explain one role that {english_subject} plays?",
                f"Core role of {english_subject}",
                ["One role of the concept", "One feature that distinguishes it from a similar concept"],
            ),
            "evidence": (
                f"What is one clue in the presentation that connects the cause and result for {english_subject}?",
                f"Evidence connecting cause and result for {english_subject}",
                ["One piece of evidence from the presentation", "Why that evidence supports the conclusion"],
            ),
            "counterexample": (
                f"What is one condition under which the explanation of {english_subject} could change?",
                f"Condition that changes {english_subject}",
                ["One condition that could change the explanation", "How the result changes under that condition"],
            ),
            "application": (
                f"What is one criterion you could use when applying {english_subject}?",
                f"Decision criterion for applying {english_subject}",
                ["One criterion from the original explanation", "Why that criterion applies to this situation"],
            ),
        }
        return english_templates[current_type]
    templates: Dict[QuestionType, tuple[str, str, List[str]]] = {
        "definition": (
            f"{subject}이 실제로 하는 역할 한 가지를 먼저 설명해 주실 수 있나요?",
            f"{subject}의 핵심 역할 확인",
            ["개념이 수행하는 역할 한 가지", "비슷한 개념과 구분되는 특징 한 가지"],
        ),
        "evidence": (
            f"{subject}에 대해 원인과 결과를 이어 주는 자료 속 단서 한 가지는 무엇인가요?",
            f"{subject}의 원인과 결과를 잇는 근거 확인",
            ["발표 자료에 제시된 근거 한 가지", "그 근거가 결론과 연결되는 이유"],
        ),
        "counterexample": (
            f"{subject}에 관한 설명이 달라질 수 있는 조건 한 가지를 먼저 떠올려 주실 수 있나요?",
            f"{subject}이 달라지는 조건 확인",
            ["설명이 달라질 수 있는 조건 한 가지", "그 조건에서 달라지는 결과"],
        ),
        "application": (
            f"{subject}을 판단할 때 사용할 수 있는 기준 한 가지는 무엇인가요?",
            f"{subject}에 적용할 판단 기준 확인",
            ["원래 설명에서 가져온 판단 기준 한 가지", "그 기준이 현재 상황과 연결되는 이유"],
        ),
    }
    return templates[current_type]


def _is_trivial_definition_retry(question: str, current_type: QuestionType) -> bool:
    """비정의형 질문이 단순 용어 정의로 후퇴한 경우 판정."""
    if current_type == "definition":
        return False
    normalized = re.sub(r"\s+", " ", question.strip())
    return bool(
        re.fullmatch(
            r".{1,60}(?:이란|란)\s*무엇인가요[?？]?",
            normalized,
        )
        or re.fullmatch(
            r".{1,60}(?:의\s*)?(?:뜻|정의)는\s*무엇인가요[?？]?",
            normalized,
        )
        or re.fullmatch(
            r"(?i)(?:what\s+is|what\s+does)\s+.{1,100}(?:mean|do)\??",
            normalized,
        )
        or re.fullmatch(r"(?i)define\s+.{1,100}\.?", normalized)
    )


def _build_unknown_retry(req: EvaluateRequest) -> EvaluateResponse:
    """무응답 문장을 제외한 사고 지원 설명과 무료 재질문 생성."""
    current_type = req.question_type or req.root_question_type or "definition"
    prompt_slides = material_context.build_prompt_slides(req.script, req.slides)
    selected_slides = material_context.select_context_slides(
        prompt_slides,
        req.context_slides,
        query=req.question_focus or req.question,
    )
    slide_context = "\n\n".join(
        f"[슬라이드 {slide.index}]\n{slide.text[:1800]}"
        for slide in selected_slides[:3]
    ) or "(관련 슬라이드 없음)"
    expected_points = "\n".join(
        f"- {point}"
        for point in req.expected_answer_points[:3]
        if point.strip()
    ) or "- 현재 질문에서 확인하려던 핵심 요소 한 가지"
    source_question = req.question.strip()
    focus = req.question_focus.strip() or source_question[:160]
    output_language_rule = (
        "Write supplement, retry_question, retry_focus, and retry_expected_answer_points in natural English. "
        "Set retry_speech_term_aliases to an empty array."
        if req.language == "en"
        else (
            "학생에게 보이는 내용은 자연스러운 한국어로 작성하세요. "
            "retry_speech_term_aliases에는 영문 기술 용어의 ko-KR 발음 후보만 넣으세요."
        )
    )

    system = (
        "당신은 발표 질의응답 연습을 돕는 평가자입니다. "
        "학생이 현재 질문에 답하지 못했으므로 질문 횟수를 차감하지 않는 재도전 기회를 한 번 제공합니다. "
        "학생이 입력한 무응답 문장은 제공되지 않으며 이전 답변을 추론하거나 언급해서는 안 됩니다. "
        "supplement에는 정답 전체를 말하지 말고, 답을 유추하는 데 필요한 전제·비교·인과관계를 2~3문장으로 설명하세요. "
        "retry_question은 현재 질문을 짧게 바꿔 반복하지 말고, 답변에 필요한 사고 과정의 바로 앞 단계 하나만 물으세요. "
        "하나의 요구만 포함하고, 발표 자료 안에서 답을 추론할 수 있어야 합니다. "
        "비정의형 질문을 단순한 용어 정의 질문으로 바꾸지 마세요. "
        "관련 슬라이드의 영문 기술 용어와 고유 명칭은 원문 그대로 유지하고 번역하지 마세요. "
        "retry_focus와 retry_expected_answer_points는 재질문 자체만 평가할 수 있도록 새로 작성하세요. "
        f"{output_language_rule} "
        'JSON만 반환: {"supplement":"<사고 지원 설명>","retry_question":"<재질문>",'
        '"retry_focus":"<재질문의 평가 초점>","retry_expected_answer_points":["<요소1>","<요소2>"],'
        '"retry_speech_term_aliases":[{"canonical":"<원문 영문 용어>",'
        '"aliases":["<한글 발음 표기>"]}],'
        '"related_slides":[<번호 1~2개>]}. '
    )
    user = (
        f"[현재 질문]\n{source_question}\n\n"
        f"[현재 질문 유형]\n{current_type}\n\n"
        f"[현재 질문 초점]\n{focus}\n\n"
        f"[현재 질문의 기대 요소]\n{expected_points}\n\n"
        f"[관련 발표 자료]\n{slide_context}\n\n"
        "학생이 스스로 답을 떠올릴 수 있도록 사고 단계를 한 단계 낮춘 재질문 계약을 생성하세요."
    )

    data: dict = {}
    try:
        data = llm_client.chat_json(
            system,
            user,
            get_model_hint(req.persona_id),
            kind="retry",
        )
    except Exception:  # noqa: BLE001
        logger.exception("LLM retry generation failed; deterministic fallback used")

    valid_slide_indices = {slide.index for slide in req.slides}
    preferred_indices = {
        index for index in req.context_slides if index in valid_slide_indices
    }
    related_slides = _parse_int_list(
        data.get("related_slides"),
        valid_values=preferred_indices or valid_slide_indices,
        limit=2,
    )
    if not related_slides and preferred_indices:
        related_slides = sorted(preferred_indices)[:2]

    fallback_question, fallback_focus, fallback_points = _fallback_unknown_retry(
        focus,
        current_type,
        req.language,
    )
    supplement_raw = data.get("supplement")
    supplement = (
        supplement_raw.strip()
        if isinstance(supplement_raw, str) and supplement_raw.strip()
        else _fallback_supplement(focus, current_type, req.language)
    )
    retry_raw = data.get("retry_question")
    retry_question = retry_raw.strip() if isinstance(retry_raw, str) else ""
    if (
        not retry_question
        or _is_duplicate_question(retry_question, [source_question], threshold=0.84)
        or _is_trivial_definition_retry(retry_question, current_type)
    ):
        retry_question = fallback_question

    retry_focus_raw = data.get("retry_focus")
    retry_focus = (
        retry_focus_raw.strip()
        if isinstance(retry_focus_raw, str) and retry_focus_raw.strip()
        else fallback_focus
    )
    retry_points = _parse_string_list(
        data.get("retry_expected_answer_points"),
        limit=3,
    ) or fallback_points
    retry_alias_source = "\n".join(
        [
            retry_question,
            *[slide.text for slide in selected_slides[:3]],
        ]
    )
    retry_speech_term_aliases = (
        []
        if req.language == "en"
        else _parse_speech_term_aliases(
            data.get("retry_speech_term_aliases"),
            source_text=retry_alias_source,
        )
    )

    return EvaluateResponse(
        answer_status="unknown",
        verdict="확인 필요",
        strengths="",
        gaps="기본 아이디어를 바탕으로 현재 질문을 한 단계 나누어 다시 생각해 보세요.",
        supplement=supplement,
        related_slides=related_slides,
        retry_question=retry_question,
        retry_question_type=current_type,
        retry_question_focus=retry_focus,
        retry_expected_answer_points=retry_points,
        retry_speech_term_aliases=retry_speech_term_aliases,
        next_action="retry_after_unknown",
        rubric={},
    )



def _fallback_unknown_closure(
    req: EvaluateRequest,
) -> str:
    """최종 개념 설명 생성 실패 시 발표 자료 기반 학습 안내."""
    points = [
        point.strip()
        for point in req.expected_answer_points[:3]
        if point.strip()
    ]
    focus = (
        req.question_focus.strip()
        or req.root_question
        or req.question
    )
    focus = re.sub(r"\s+", " ", focus).strip()[:180]

    if req.language == "en":
        if points:
            joined = ", ".join(points)
            return (
                f"The key points for this question are {joined}. Review the definition and role of "
                f"{focus or 'the key concept'}, and the relationship explicitly requested by the question."
            )
        return (
            f"This question checks your understanding of {focus or 'the relevant key concept'}. "
            "Review its definition, role, and relationship to the other concepts on the relevant slides."
        )

    if points:
        joined = ", ".join(points)
        return (
            f"이 질문에서 확인해야 할 핵심은 {joined}입니다. "
            f"{focus}의 정의와 역할, 질문에서 요구한 연결 관계를 "
            "발표 자료에서 다시 확인해 주세요."
        )

    return (
        f"이 질문은 {focus or '관련 핵심 개념'}에 대한 이해를 확인합니다. "
        "관련 슬라이드에서 개념의 정의, 역할, 다른 개념과의 관계를 "
        "다시 정리해 주세요."
    )


def _build_unknown_closure(
    req: EvaluateRequest,
) -> EvaluateResponse:
    """쉬운 재질문에도 답하지 못한 경우 개념 설명과 학습 안내 생성."""
    prompt_slides = material_context.build_prompt_slides(
        req.script,
        req.slides,
    )
    selected_slides = material_context.select_context_slides(
        prompt_slides,
        req.context_slides,
        query=req.question_focus or req.root_question or req.question,
    )
    slide_context = "\n\n".join(
        f"[슬라이드 {slide.index}]\n{slide.text[:1800]}"
        for slide in selected_slides[:3]
    ) or "(관련 슬라이드 없음)"
    expected_points = "\n".join(
        f"- {point}"
        for point in req.expected_answer_points[:3]
        if point.strip()
    ) or "- 질문에서 확인하려던 핵심 개념과 역할"
    output_language_rule = (
        "Write supplement in clear, natural English."
        if req.language == "en"
        else "supplement는 자연스러운 한국어로 작성하세요."
    )

    system = (
        "당신은 발표 질의응답 학습을 마무리하는 설명자입니다. "
        "학생이 원질문에 답하지 못해 힌트와 쉬운 재질문을 받았지만 "
        "재질문에도 답하지 못했습니다. 새 질문을 만들지 마세요. "
        "supplement에는 관련 발표 자료만 근거로 핵심 개념의 정의, 역할, "
        "질문에서 요구한 관계를 2~4문장으로 명확히 설명하세요. "
        "정답을 숨기는 힌트가 아니라 학습을 위한 개념 설명이어야 합니다. "
        "자료에 없는 사실은 만들지 마세요. "
        "영문 기술 용어, 프로토콜명, 모드명, 알고리즘명, 약어는 "
        "슬라이드 원문 그대로 유지하고 한국어로 번역하지 마세요. "
        f"{output_language_rule} "
        'JSON만 반환: {"supplement":"<개념 설명>",'
        '"related_slides":[<번호 1~3개>]}.'
    )
    user = (
        f"[원질문]\n{req.root_question or req.question}\n\n"
        f"[쉬운 재질문]\n{req.question}\n\n"
        f"[질문 초점]\n{req.question_focus}\n\n"
        f"[기대 답변 요소]\n{expected_points}\n\n"
        f"[관련 발표 자료]\n{slide_context}\n\n"
        "학생이 이후에 다시 공부할 수 있도록 개념 설명을 작성하세요."
    )

    data: dict = {}
    try:
        data = llm_client.chat_json(
            system,
            user,
            get_model_hint(req.persona_id),
            kind="unknown_closure",
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "LLM unknown closure generation failed; fallback used"
        )

    supplement_raw = data.get("supplement")
    supplement = (
        supplement_raw.strip()
        if isinstance(supplement_raw, str)
        and supplement_raw.strip()
        else _fallback_unknown_closure(req)
    )

    valid_slide_indices = {slide.index for slide in req.slides}
    preferred_indices = {
        index
        for index in req.context_slides
        if index in valid_slide_indices
    }
    related_slides = _parse_int_list(
        data.get("related_slides"),
        valid_values=preferred_indices or valid_slide_indices,
        limit=3,
    )
    if not related_slides and preferred_indices:
        related_slides = sorted(preferred_indices)[:3]

    return EvaluateResponse(
        answer_status="unknown",
        verdict="확인 필요",
        strengths="",
        gaps="이 질문과 관련된 개념을 발표 전에 다시 학습해 주세요.",
        supplement=supplement,
        related_slides=related_slides,
        next_action=_next_action_after_current_question(req),
        rubric={},
    )


_GAP_CLEANUP_SUFFIXES = (
    "구체적인 설명이 부족합니다",
    "구체적 설명이 부족합니다",
    "설명이 부족합니다",
    "근거가 부족합니다",
    "예시가 부족합니다",
    "언급이 부족합니다",
    "부족합니다",
    "필요합니다",
)


def _extract_gap_focus(raw_gap: str) -> str:
    """평가 보완점에서 다음 질문에 사용할 핵심 누락 추출."""
    normalized = re.sub(
        r"[✅⚠️❗️]+",
        " ",
        raw_gap or "",
    )
    normalized = re.sub(r"\s+", " ", normalized).strip(" .,:;-")
    if not normalized:
        return ""

    # 여러 보완점 중 첫 번째 구체 항목 우선 선택
    first_part = re.split(r"(?<=[.!?。])\s+|[•·]\s*", normalized)[0]
    first_part = re.sub(
        r"^(다만|하지만|그러나|또한|그리고)\s*",
        "",
        first_part,
    ).strip(" .,:;-")

    for suffix in _GAP_CLEANUP_SUFFIXES:
        if first_part.endswith(suffix):
            first_part = first_part[: -len(suffix)].strip(" .,:;-")
            break

    first_part = re.sub(r"(라는|이라는|한다는|된다는|있다는)$", "", first_part)
    return first_part[:180].strip(" .,:;-")


def _has_meaningful_gap(raw_gap: str) -> bool:
    """후속 질문으로 확인할 가치가 있는 구체 보완점 판정."""
    focus = _extract_gap_focus(raw_gap)
    if len(focus) < 6:
        return False

    generic_phrases = {
        "보완할 점이 없음",
        "특별한 보완점이 없음",
        "충분히 설명함",
        "전반적으로 적절함",
        "없음",
    }
    return focus not in generic_phrases


def _focus_tokens(text: str) -> set[str]:
    """보완점 선택용 핵심 토큰 집합 생성."""
    stopwords = {
        "구체적인",
        "구체적으로",
        "명확히",
        "설명",
        "언급",
        "부족",
        "필요",
        "부분",
        "내용",
        "대한",
        "관련",
        "경우",
        "특히",
        "그리고",
        "또한",
        "및",
    }
    return {
        token.lower()
        for token in _QUESTION_TOKEN_PATTERN.findall(text or "")
        if token.lower() not in stopwords
    }


def _gap_point_score(
    raw_gap: str,
    point: str,
) -> float:
    """평가 보완점과 기대 요소의 연관성 점수 계산."""
    gap_tokens = _focus_tokens(raw_gap)
    point_tokens = _focus_tokens(point)
    if not gap_tokens or not point_tokens:
        return 0.0

    return len(gap_tokens & point_tokens) / len(point_tokens)


def _clean_single_focus(text: str) -> str:
    """후속 질문용 단일 초점 문구 정리."""
    normalized = re.sub(r"\s+", " ", text or "").strip(" .,:;-")
    normalized = re.sub(
        r"^(특히|다만|하지만|그러나|또한|그리고)\s*",
        "",
        normalized,
    )
    normalized = re.sub(
        r"(에 대한|에 관한)?\s*"
        r"(구체적인|구체적)?\s*"
        r"(설명|언급|근거|예시)?\s*"
        r"(이|가)?\s*"
        r"(부족합니다|부족함|필요합니다|필요함)$",
        "",
        normalized,
    ).strip(" .,:;-")

    # 나열형 문구의 첫 항목만 선택
    normalized = re.sub(
        r"(정의|특징|이유|역할|근거|방법|과정|조건|한계|차이|사례|적용)"
        r"(?:과|와)"
        r"(정의|특징|이유|역할|근거|방법|과정|조건|한계|차이|사례|적용)",
        r"\1, \2",
        normalized,
    )
    parts = re.split(
        r"\s*(?:,|;|/|\b및\b|\b그리고\b|\b또는\b)\s*",
        normalized,
    )
    candidates = [
        part.strip(" .,:;-")
        for part in parts
        if len(part.strip(" .,:;-")) >= 3
    ]
    selected = candidates[0] if candidates else normalized
    return selected[:100].strip(" .,:;-")


def _gap_repeats_covered_expected_point(
    req: EvaluateRequest,
    raw_gap: str,
    point_assessments: Dict[int, bool],
) -> bool:
    """이미 충족된 요소를 보완점이 다시 누락으로 지목했는지 확인합니다."""
    assessed_indices = [
        index
        for index, point in enumerate(req.expected_answer_points)
        if point.strip()
    ][:3]
    # 모델이 프롬프트에 제시된 요소를 모두 판정한 경우에만
    # 잘못된 gaps를 무시합니다. 일부 판정만으로 실제 누락을 숨기지 않습니다.
    if (
        not assessed_indices
        or any(
            point_assessments.get(index) is not True
            for index in assessed_indices
        )
    ):
        return False

    return _gap_targets_covered_expected_point(
        req,
        raw_gap,
        point_assessments,
    )


_MISSING_CLAIM_MARKERS = (
    "누락",
    "빠졌",
    "빠져",
    "언급하지",
    "말하지",
    "포함하지",
    "제시하지",
    "답하지",
)
_SUPPORT_GAP_MARKERS = (
    "근거",
    "이유",
    "왜",
    "논리",
    "연결",
    "과정",
    "메커니즘",
    "수치",
    "예시",
)


def _gap_targets_covered_expected_point(
    req: EvaluateRequest,
    raw_gap: str,
    point_assessments: Dict[int, bool],
) -> bool:
    """보완점이 설명 깊이가 아니라 이미 말한 명제의 누락을 주장하는지 판정합니다."""
    normalized_gap = re.sub(r"\s+", " ", raw_gap).strip()
    if (
        not normalized_gap
        or not any(
            marker in normalized_gap
            for marker in _MISSING_CLAIM_MARKERS
        )
        or any(
            marker in normalized_gap
            for marker in _SUPPORT_GAP_MARKERS
        )
    ):
        return False

    gap_focus = _extract_gap_focus(raw_gap)
    if not gap_focus:
        return False

    covered_score = max(
        (
            _gap_point_score(gap_focus, point)
            for index, point in enumerate(req.expected_answer_points)
            if point.strip()
            and point_assessments.get(index) is True
        ),
        default=0.0,
    )
    uncovered_score = max(
        (
            _gap_point_score(gap_focus, point)
            for index, point in enumerate(req.expected_answer_points)
            if point.strip()
            and point_assessments.get(index) is False
        ),
        default=0.0,
    )
    return (
        covered_score >= 0.5
        and covered_score > uncovered_score
    )


def _rewrite_gap_as_user_feedback(
    req: EvaluateRequest,
    uncovered_indices: List[int],
) -> Optional[str]:
    """내부 기대 요소를 사용자용 한국어 보완 설명으로 다시 작성합니다."""
    if not uncovered_indices:
        return None

    prompt_slides = material_context.build_prompt_slides(req.script, req.slides)
    selected_slides = material_context.select_context_slides(
        prompt_slides,
        req.context_slides,
        query=req.question_focus or req.question,
    )
    slide_context = "\n\n".join(
        f"[슬라이드 {slide.index}]\n{slide.text[:1200]}"
        for slide in selected_slides[:3]
    ) or "(관련 슬라이드 없음)"
    missing_points = "\n".join(
        f"- {req.expected_answer_points[index]}"
        for index in uncovered_indices
        if 0 <= index < len(req.expected_answer_points)
        and req.expected_answer_points[index].strip()
    )
    if not missing_points:
        return None

    system = (
        "당신은 발표 질의응답의 사용자용 보완 설명을 작성합니다. 질문, 학생 답변, "
        "내부 평가 요소, 관련 슬라이드를 근거로 부족한 핵심 한 가지를 자연스러운 "
        "한국어 1~2문장으로 설명하세요. 사용자가 별도 자료를 보지 않아도 이해할 수 "
        "있어야 합니다. 내부 평가 요소나 슬라이드의 원문 문장, 조건식, 식별자, 기호를 "
        "그대로 복사해 붙이지 마세요. 기술 용어·고유 명칭은 꼭 필요할 때만 원문 표기를 "
        "유지하고, 그 용어의 역할이나 빠진 관계를 한국어로 설명하세요. 문맥으로 역할을 "
        "확정할 수 없는 표기는 사용하지 마세요. 자료에 없는 사실을 추가하지 마세요. "
        'JSON만 반환: {"gaps":"<자기완결적인 한국어 보완 설명>"}.'
    )
    user = (
        f"[질문]\n{req.question[:700]}\n\n"
        f"[학생 답변]\n{req.answer[:1800]}\n\n"
        f"[내부 미충족 요소]\n{missing_points}\n\n"
        f"[관련 발표 자료]\n{slide_context}"
    )
    try:
        data = llm_client.chat_json(
            system,
            user,
            get_model_hint(req.persona_id),
            kind="evaluate",
        )
    except Exception:  # noqa: BLE001
        logger.exception("User-facing gap rewrite failed")
        return None

    rewritten = data.get("gaps")
    if not isinstance(rewritten, str):
        return None
    return rewritten.strip()[:600] or None


def _normalize_semantic_consistency(
    req: EvaluateRequest,
    evaluation_data: dict,
) -> dict:
    """요소별 의미 판정과 정반대인 '누락' 피드백만 보수적으로 교정합니다."""
    point_assessments = _parse_expected_point_assessments(
        evaluation_data.get("expected_point_assessments"),
        req.expected_answer_points,
        req.answer,
    )
    out_of_scope_indices = {
        index
        for index in evaluation_data.get(
            "_out_of_scope_expected_point_indices",
            [],
        )
        if isinstance(index, int)
        and not isinstance(index, bool)
        and 0 <= index < len(req.expected_answer_points)
    }
    effective_assessments = dict(point_assessments)
    for index in out_of_scope_indices:
        if index in effective_assessments:
            effective_assessments[index] = True

    displayed_indices = [
        index
        for index, point in enumerate(req.expected_answer_points)
        if point.strip()
    ][:3]
    required_indices = [
        index
        for index in displayed_indices
        if index not in out_of_scope_indices
    ]
    if (
        out_of_scope_indices
        and all(
            effective_assessments.get(index) is True
            for index in required_indices
        )
    ):
        normalized = dict(evaluation_data)
        normalized["verdict"] = "충분"
        normalized["gaps"] = "없음"
        if not str(normalized.get("strengths", "")).strip():
            normalized["strengths"] = (
                "질문에서 요구한 핵심 요소를 자신의 말로 설명했습니다."
            )
        rubric = _parse_rubric(normalized.get("rubric"))
        for axis in _RUBRIC_AXES:
            if rubric.get(axis) in {None, "부족"}:
                rubric[axis] = "보통"
        normalized["rubric"] = rubric
        return normalized

    raw_gap = str(evaluation_data.get("gaps", "")).strip()
    if not _gap_targets_covered_expected_point(
        req,
        raw_gap,
        effective_assessments,
    ):
        return evaluation_data

    if not displayed_indices or any(
        index not in effective_assessments
        for index in displayed_indices
    ):
        return evaluation_data

    normalized = dict(evaluation_data)
    uncovered_indices = [
        index
        for index in displayed_indices
        if effective_assessments.get(index) is False
    ]
    verdict = str(normalized.get("verdict", "")).strip()

    if uncovered_indices and verdict == "충분":
        # 모델이 해당 요소를 선택 사항으로 보고 충분 판정을 유지했다면
        # covered 요소를 누락이라 한 문장만 제거합니다.
        normalized["gaps"] = "없음"
        return normalized

    if uncovered_indices:
        normalized["verdict"] = "부분 충족"
        normalized["gaps"] = (
            _rewrite_gap_as_user_feedback(req, uncovered_indices)
            or "질문에서 요구한 핵심 조건 중 답변에 드러나지 않은 부분을 더 분명히 설명해 주세요."
        )
        if not str(normalized.get("strengths", "")).strip():
            normalized["strengths"] = (
                "질문의 일부 핵심 요소를 자신의 말로 설명했습니다."
            )
        rubric = _parse_rubric(normalized.get("rubric"))
        if rubric.get("직접성") == "부족":
            rubric["직접성"] = "보통"
        normalized["rubric"] = rubric
        return normalized

    # 모든 제시 요소가 실제 답변 원문 근거와 함께 covered일 때만
    # 모순된 누락 피드백을 충분/없음으로 정규화합니다.
    normalized["verdict"] = "충분"
    normalized["gaps"] = "없음"
    if not str(normalized.get("strengths", "")).strip():
        normalized["strengths"] = (
            "질문의 핵심 요소를 자신의 말로 설명했습니다."
        )
    rubric = _parse_rubric(normalized.get("rubric"))
    for axis in _RUBRIC_AXES:
        if rubric.get(axis) in {None, "부족"}:
            rubric[axis] = "보통"
    normalized["rubric"] = rubric
    return normalized


def _audit_uncovered_expected_points(
    req: EvaluateRequest,
    evaluation_data: dict,
) -> dict:
    """최초 평가가 놓친 바꿔 말하기·작동 설명의 의미 충족 여부를 재검증합니다."""
    initial_assessments = _parse_expected_point_assessments(
        evaluation_data.get("expected_point_assessments"),
        req.expected_answer_points,
        req.answer,
    )
    uncovered_indices = [
        index
        for index, point in enumerate(req.expected_answer_points)
        if point.strip() and initial_assessments.get(index) is False
    ][:3]
    if not uncovered_indices:
        return evaluation_data

    prompt_slides = material_context.build_prompt_slides(
        req.script,
        req.slides,
    )
    selected_slides = material_context.select_context_slides(
        prompt_slides,
        req.context_slides,
        query=req.question_focus or req.question,
    )
    slide_context = "\n\n".join(
        f"[슬라이드 {slide.index}]\n{slide.text[:1400]}"
        for slide in selected_slides[:3]
    ) or "(관련 슬라이드 없음)"
    points = "\n".join(
        f"- point_index {index}: {req.expected_answer_points[index]}"
        for index in uncovered_indices
    )

    system = (
        "당신은 발표 답변의 의미 동등성만 독립적으로 재검증하는 판정자입니다. "
        "최초 평가가 미충족으로 본 요소만 확인하세요. 먼저 해당 요소가 직전 질문에서 "
        "명시적으로 요구된 필수 답변인지 판단하세요. 발표 자료에 관련 내용이 있다는 이유만으로 "
        "질문이 묻지 않은 배경·장애 유형·장점·절차를 필수로 만들지 마세요. "
        "질문의 범위를 벗어나면 required_by_question=false입니다. "
        "필수 요소라면 정확한 문구 일치를 요구하지 마세요. "
        "학생이 표준 개념이나 방법을 이름으로 말하고 그 작동 방식·결과·구체적 상황을 설명하여 "
        "기대 요소를 논리적으로 함의했다면 covered=true입니다. 같은 단어만 등장했거나 "
        "여러 해석이 가능하면 covered=false입니다. 발음이 깨진 STT 전사는 질문과 자료에서 "
        "하나의 원문 용어로 확정될 때만 복원하세요. 학생이 말하지 않은 내용을 보태지 마세요. "
        "covered=true인 answer_evidence는 학생 답변에서 공백까지 그대로 복사한 짧은 연속 구절이어야 "
        "하고, covered=false이면 빈 문자열이어야 합니다. "
        'JSON만 반환: {"expected_point_assessments": ['
        '{"point_index": <번호>, "required_by_question": <true|false>, '
        '"covered": <true|false>, '
        '"answer_evidence": "<학생 답변의 연속 원문 또는 빈 문자열>"}]}.'
    )
    user = (
        f"[질문]\n{req.question}\n\n"
        f"[학생 답변 원문]\n{req.answer}\n\n"
        f"[재검증할 기대 요소]\n{points}\n\n"
        f"[관련 발표 자료]\n{slide_context}"
    )

    try:
        audit_data = llm_client.chat_json(
            system,
            user,
            get_model_hint(req.persona_id),
            kind="evaluate",
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "Semantic coverage audit failed; initial evaluation retained"
        )
        return evaluation_data

    def item_index(item: dict) -> Optional[int]:
        value = item.get("point_index")
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    audited = _parse_expected_point_assessments(
        audit_data.get("expected_point_assessments"),
        req.expected_answer_points,
        req.answer,
    )
    raw_audit_items = audit_data.get("expected_point_assessments")
    out_of_scope_indices = {
        index
        for item in raw_audit_items
        if isinstance(item, dict)
        and item.get("required_by_question") is False
        and (index := item_index(item)) in uncovered_indices
    } if isinstance(raw_audit_items, list) else set()
    newly_covered = {
        index
        for index in uncovered_indices
        if audited.get(index) is True
    }
    if not newly_covered and not out_of_scope_indices:
        return evaluation_data

    original_items = evaluation_data.get("expected_point_assessments")
    retained_items = [
        item
        for item in original_items
        if isinstance(item, dict)
        and item_index(item) not in newly_covered
    ] if isinstance(original_items, list) else []
    audited_items = [
        item
        for item in audit_data.get("expected_point_assessments", [])
        if isinstance(item, dict)
        and item_index(item) in newly_covered
    ]

    normalized = dict(evaluation_data)
    normalized["expected_point_assessments"] = [
        *retained_items,
        *audited_items,
    ]
    existing_out_of_scope = normalized.get(
        "_out_of_scope_expected_point_indices",
        [],
    )
    normalized["_out_of_scope_expected_point_indices"] = sorted({
        *(
            index
            for index in existing_out_of_scope
            if isinstance(index, int) and not isinstance(index, bool)
        ),
        *out_of_scope_indices,
    })
    return normalized


_LOGIC_GAP_MARKERS = (
    "모순",
    "앞뒤",
    "논리",
    "연결되지",
    "연결이 부족",
    "인과가",
)


def _normalize_rubric_consistency(
    req: EvaluateRequest,
    evaluation_data: dict,
) -> dict:
    """판정·강점과 모순되는 전 축 부족 루브릭을 최소 범위로 정규화합니다."""
    verdict = str(evaluation_data.get("verdict", "")).strip()
    if verdict not in {"충분", "부분 충족"}:
        return evaluation_data

    normalized = dict(evaluation_data)
    rubric = _parse_rubric(normalized.get("rubric"))

    if verdict == "충분":
        for axis in _RUBRIC_AXES:
            if rubric.get(axis) in {None, "부족"}:
                rubric[axis] = "보통"
        normalized["rubric"] = rubric
        return normalized

    if rubric.get("직접성") in {None, "부족"}:
        rubric["직접성"] = "보통"

    gaps = str(normalized.get("gaps", "")).strip()
    strengths = str(normalized.get("strengths", "")).strip()
    if (
        strengths
        and not any(
            marker in gaps
            for marker in _LOGIC_GAP_MARKERS
        )
        and rubric.get("논리") in {None, "부족"}
    ):
        rubric["논리"] = "보통"

    current_type = req.question_type or req.root_question_type
    if (
        current_type != "evidence"
        and rubric.get("근거") in {None, "부족"}
    ):
        rubric["근거"] = "보통"

    normalized["rubric"] = rubric
    return normalized


def _select_single_followup_focus(
    req: EvaluateRequest,
    raw_gap: str,
    point_assessments: Dict[int, bool] | None = None,
) -> str:
    """학생 답변에서 누락된 기대 요소 한 가지 선택."""
    assessments = point_assessments or {}
    expected_candidates: List[tuple[int, str]] = []
    for index, point in enumerate(req.expected_answer_points):
        cleaned = _clean_single_focus(point)
        if cleaned and assessments.get(index) is not True:
            expected_candidates.append((index, cleaned))

    if expected_candidates:
        ranked = sorted(
            expected_candidates,
            key=lambda candidate: (
                _gap_point_score(raw_gap, candidate[1]),
                assessments.get(candidate[0]) is False,
            ),
            reverse=True,
        )
        best_index, best = ranked[0]
        if (
            _gap_point_score(raw_gap, best) > 0
            or assessments.get(best_index) is False
        ):
            return best

    # 평가 문장에 여러 항목이 있으면 가장 먼저 제시된 단일 항목 선택
    gap_sentences = [
        sentence.strip()
        for sentence in re.split(
            r"(?<=[.!?。！？])\s+",
            raw_gap or "",
        )
        if sentence.strip()
    ]
    for sentence in reversed(gap_sentences):
        candidate = _clean_single_focus(sentence)
        if candidate and len(candidate) >= 4:
            return candidate

    fallback = _clean_single_focus(
        req.question_focus or _extract_gap_focus(raw_gap)
    )
    return fallback or "앞선 질문의 핵심 개념"


_MEDIUM_REQUEST_TERMS = (
    "정의",
    "특징",
    "이유",
    "역할",
    "근거",
    "방법",
    "과정",
    "조건",
    "한계",
    "차이",
    "사례",
    "적용",
    "영향",
)


def _is_compound_medium_followup(question: str) -> bool:
    """보통 난이도 복합 요구 질문 판정."""
    normalized = re.sub(r"\s+", " ", question or "").strip()
    if not normalized:
        return True

    if len(normalized) > 95:
        return True

    # 쉼표 나열 또는 접속사를 이용한 다중 요구 판정
    if normalized.count(",") >= 2:
        return True
    if re.search(r"\b(?:및|그리고)\b", normalized):
        return True

    request_count = sum(
        1
        for term in _MEDIUM_REQUEST_TERMS
        if term in normalized
    )
    if request_count >= 3:
        return True

    if re.search(
        r"(정의|특징|이유|역할|근거|방법|과정|조건|한계|차이)"
        r"(?:과|와)"
        r"(정의|특징|이유|역할|근거|방법|과정|조건|한계|차이)",
        normalized,
    ):
        return True

    if re.search(
        r"(방금 답변|부족했던|부족한 부분|보완해|한 가지 핵심만)",
        normalized,
    ):
        return True

    return False


def _question_addresses_gap(
    question: str,
    gap_focus: str,
) -> bool:
    """생성 질문이 평가 보완점의 핵심 토큰을 실제로 포함하는지 판정."""
    question_tokens = _question_tokens(question)
    gap_tokens = {
        token
        for token in _question_tokens(gap_focus)
        if len(token) >= 2
    }
    if not gap_tokens:
        return True

    return bool(question_tokens & gap_tokens)


def _contains_hangul(text: str) -> bool:
    """영문 질문 계약을 깨는 한글 포함 여부."""
    return bool(re.search(r"[가-힣]", text or ""))


def _natural_followup_subject(
    req: EvaluateRequest,
    gap_focus: str,
) -> str:
    """원질문과 평가 초점에서 자연스러운 후속 질문 주제 추출."""
    candidates = [
        req.question_focus,
        req.root_question or "",
        req.question,
    ]
    gap_tokens = _focus_tokens(gap_focus)

    for candidate in candidates:
        cleaned = _clean_single_focus(candidate)
        if not cleaned:
            continue

        candidate_tokens = _focus_tokens(cleaned)
        if not candidate_tokens:
            continue

        # 보완점과 거의 같은 문구는 연결 대상에서 제외
        overlap = len(gap_tokens & candidate_tokens) / max(
            1,
            min(len(gap_tokens), len(candidate_tokens)),
        )
        if overlap < 0.75:
            return cleaned[:80]

    return ""


def _fallback_gap_followup(
    req: EvaluateRequest,
    gap_focus: str,
    current_type: QuestionType,
) -> tuple[str, QuestionType, str, List[str]]:
    """실제 발표 현장처럼 단일 보완점을 자연스럽게 묻는 폴백 생성."""
    concise_gap = _clean_single_focus(gap_focus)[:90]
    subject = _natural_followup_subject(req, concise_gap)

    if req.language == "en":
        english_subject = subject or "the main claim"
        english_questions: Dict[QuestionType, str] = {
            "evidence": f"Why does {concise_gap} support {english_subject}?",
            "application": f"How would you apply {concise_gap} to {english_subject}?",
            "counterexample": f"Under what condition might {concise_gap} not hold for {english_subject}?",
            "definition": f"What role does {concise_gap} play in {english_subject}?",
        }
        return (
            english_questions[current_type],
            current_type,
            concise_gap,
            [concise_gap],
        )

    if current_type == "evidence":
        if subject:
            question = (
                f"{concise_gap}가 {subject}를 뒷받침하는 이유를 "
                "설명해 주실 수 있나요?"
            )
        else:
            question = (
                f"{concise_gap}가 중요하다고 볼 수 있는 근거를 "
                "설명해 주실 수 있나요?"
            )
    elif current_type == "application":
        if subject:
            question = (
                f"{concise_gap}를 {subject}와 연결하면 "
                "어떻게 적용할 수 있는지 설명해 주실 수 있나요?"
            )
        else:
            question = (
                f"{concise_gap}가 실제 상황에서 어떻게 활용되는지 "
                "설명해 주실 수 있나요?"
            )
    elif current_type == "counterexample":
        if subject:
            question = (
                f"{concise_gap}가 {subject}에서 성립하지 않을 수 있는 "
                "조건을 설명해 주실 수 있나요?"
            )
        else:
            question = (
                f"{concise_gap}가 제한될 수 있는 조건을 "
                "설명해 주실 수 있나요?"
            )
    else:
        if subject:
            question = (
                f"{concise_gap}가 {subject}에서 어떤 역할을 하는지 "
                "설명해 주실 수 있나요?"
            )
        else:
            question = (
                f"{concise_gap}가 왜 중요한지 "
                "설명해 주실 수 있나요?"
            )

    return (
        question,
        current_type,
        concise_gap,
        [concise_gap],
    )



def _fallback_required_followup(
    question_focus: str,
    current_type: QuestionType,
    language: str = "ko",
) -> tuple[str, QuestionType, str, List[str]]:
    """정상 답변 이후 심화·확장용 꼬리질문 계약 생성."""
    focus = re.sub(r"\s+", " ", question_focus.strip())[:120]
    subject = focus or "앞선 답변의 핵심 내용"
    next_type = _TYPE_TRANSITIONS[current_type]
    if language == "en":
        english_subject = focus or "the main point of your previous answer"
        english_templates: Dict[QuestionType, tuple[str, QuestionType, str, List[str]]] = {
            "definition": (
                f"Could you give one example from the presentation that demonstrates {english_subject}?",
                "application",
                f"Example demonstrating {english_subject}",
                ["One example connected to the definition", "Why the example demonstrates the concept"],
            ),
            "evidence": (
                "Under what condition could the evidence you just gave become weaker or lead to a different conclusion?",
                "counterexample",
                f"Condition that weakens the evidence for {english_subject}",
                ["One condition that weakens the evidence", "How the conclusion changes under that condition"],
            ),
            "counterexample": (
                "What could be done to reduce or address the exception you just described?",
                "application",
                f"Response to the exception for {english_subject}",
                ["One way to address the exception", "Why that approach would work"],
            ),
            "application": (
                "What evidence from the presentation supports the application you just proposed?",
                "evidence",
                f"Evidence supporting the application of {english_subject}",
                ["Evidence from the presentation", "How the evidence supports the proposed application"],
            ),
        }
        return english_templates[current_type]
    templates: Dict[QuestionType, tuple[str, QuestionType, str, List[str]]] = {
        "definition": (
            f"방금 설명한 {subject}이 실제 발표 사례에서 어떻게 드러나는지 한 가지 예로 설명해 주실 수 있나요?",
            "application",
            f"{subject}의 실제 사례 확장",
            ["앞선 정의와 연결되는 사례 한 가지", "사례가 해당 개념을 보여 주는 이유"],
        ),
        "evidence": (
            "방금 제시한 근거가 약해지거나 결론이 달라질 수 있는 조건은 무엇인가요?",
            "counterexample",
            f"{subject}의 근거가 약해지는 조건 확인",
            ["근거가 약해지는 조건 한 가지", "그 조건에서 결론이 달라지는 방식"],
        ),
        "counterexample": (
            "방금 제시한 예외 상황을 줄이거나 보완하기 위해 어떤 방법을 적용할 수 있나요?",
            "application",
            f"{subject}의 예외 조건에 대한 보완 방법 확장",
            ["예외 상황을 줄이는 보완 방법", "보완 방법이 작동하는 이유"],
        ),
        "application": (
            "방금 제안한 적용 방식이 타당하다고 판단할 수 있는 발표 자료 속 근거는 무엇인가요?",
            "evidence",
            f"{subject}의 적용 결과를 뒷받침하는 근거 확인",
            ["적용 결과를 뒷받침하는 자료 속 근거", "근거와 적용 결과의 연결"],
        ),
    }
    return templates[current_type]


def _build_followup(
    req: EvaluateRequest,
    evaluation_data: dict,
) -> tuple[
    str,
    QuestionType,
    str,
    List[str],
    List[SpeechTermAlias],
] | None:
    """답변의 가장 중요한 보완점을 우선 확인하는 꼬리질문 생성."""
    current_type = req.question_type or req.root_question_type or "definition"
    raw_gap = str(evaluation_data.get("gaps", "")).strip()
    point_assessments = _parse_expected_point_assessments(
        evaluation_data.get("expected_point_assessments"),
        req.expected_answer_points,
        req.answer,
    )
    has_meaningful_gap = (
        _has_meaningful_gap(raw_gap)
        and not _gap_repeats_covered_expected_point(
            req,
            raw_gap,
            point_assessments,
        )
    )
    if not has_meaningful_gap:
        gap_focus = ""
    elif req.difficulty == "medium":
        gap_focus = _select_single_followup_focus(
            req,
            raw_gap,
            point_assessments,
        )
    else:
        gap_focus = _extract_gap_focus(raw_gap)

    if req.language == "en" and has_meaningful_gap:
        # 한국어 평가 문구를 영문 꼬리질문에 직접 삽입하지 않습니다.
        # 질문 생성 단계에서 이미 영어로 작성된 기대 요소를 우선 사용합니다.
        gap_focus = next(
            (
                point.strip()
                for index, point in enumerate(req.expected_answer_points)
                if point.strip()
                and point_assessments.get(index) is False
            ),
            req.question_focus.strip() or req.question.strip(),
        )

    if has_meaningful_gap:
        (
            fallback_question,
            fallback_type,
            fallback_focus,
            fallback_points,
        ) = _fallback_gap_followup(
            req,
            gap_focus,
            current_type,
        )
    else:
        (
            fallback_question,
            fallback_type,
            fallback_focus,
            fallback_points,
        ) = _fallback_required_followup(
            req.question_focus,
            current_type,
            req.language,
        )
    prompt_slides = material_context.build_prompt_slides(req.script, req.slides)
    selected_slides = material_context.select_context_slides(
        prompt_slides,
        req.context_slides,
        query=req.question_focus or req.question,
    )
    slide_context = "\n\n".join(
        f"[슬라이드 {slide.index}]\n{slide.text[:1600]}"
        for slide in selected_slides[:3]
    ) or "(관련 슬라이드 없음)"

    followup_policy = get_question_policy_prompt(
        req.persona_id,
        req.difficulty,
    )
    difficulty_followup_rule = {
        "easy": (
            "쉬움에서는 정상 꼬리질문을 만들지 않습니다. "
            "이 함수가 호출되었다면 자료에 직접 나온 한 가지 확인만 작성하세요."
        ),
        "medium": (
            "보통에서는 평가 축 두 개 이상이 부족한 경우에만 호출됩니다. "
            "[후속 질문 핵심] 한 가지만 질문하세요. "
            "전체 평가 보완점의 다른 항목을 질문에 추가하지 마세요. "
            "질문 범위를 원질문보다 넓히지 마세요. "
            "정의·특징·이유·환경·방법 등을 한 문장에 함께 요구하지 마세요. "
            "쉼표 나열이나 '및', '그리고'로 여러 요구를 연결하지 마세요. "
            "기대 답변 요소도 한 개만 작성하세요. "
            "출력 질문에는 '방금 답변에서', '부족했던', '보완해 주세요', "
            "'한 가지 핵심만' 같은 평가 시스템의 메타 표현을 사용하지 마세요. "
            "실제 교수나 청중이 묻듯이 '~가 왜 중요한지', "
            "'~와 어떤 관련이 있는지', '~에서 어떤 역할을 하는지'처럼 "
            "자연스러운 질문으로 작성하세요. "
            "주요 질문 유형 또는 보조 질문 유형만 사용하세요."
        ),
        "hard": (
            "어려움에서는 같은 핵심 주제를 한 단계 깊게 검증하세요. "
            "전제, 성립 조건, 실패 조건, 개념 경계, 다른 환경 적용 중 한 축만 선택하세요. "
            "제한 질문 유형은 자료 전체의 논리를 확인하는 데 필요한 경우 사용할 수 있습니다. "
            "외부 사실을 단정하지 말고 자료 밖 확장은 가정형으로 표현하세요."
        ),
    }.get(req.difficulty, "")
    output_language_rule = (
        "Write followup, followup_focus, and followup_expected_answer_points in natural English. "
        "Never copy Korean evaluation wording into those fields; use the English follow-up focus and source terms. "
        "Set followup_speech_term_aliases to an empty array."
        if req.language == "en"
        else (
            "학생에게 보이는 내용은 자연스러운 한국어로 작성하세요. "
            "followup_speech_term_aliases에는 영문 기술 용어의 ko-KR 발음 후보만 넣으세요."
        )
    )

    system = (
        "당신은 발표 질의응답의 꼬리질문을 만드는 평가자입니다. "
        "학생은 앞선 기본 질문에 내용 있는 답변을 했습니다. "
        "앞선 질문을 다시 말하거나 같은 정의를 반복해서 묻지 마세요. "
        "[후속 질문 핵심]이 구체적으로 제공되면 다른 주제로 확장하지 말고, "
        "그 개념을 원질문 또는 발표 자료와 연결해 자연스럽게 묻는 질문 하나를 만드세요. "
        "평가 결과를 학생에게 설명하거나 보완을 지시하는 문구가 아니라, "
        "실제 발표 현장에서 교수나 청중이 이어 묻는 문장이어야 합니다. "
        "우선 보완점이 없을 때만 근거, 조건·한계, 반례, 다른 상황 적용 중 "
        "가장 가치 있는 방향 하나를 선택하세요. "
        "질문은 발표 자료와 학생 답변으로 답할 수 있어야 하며, 한 문장에 요구를 하나만 포함하세요. "
        "관련 슬라이드의 영문 기술 용어와 고유 명칭은 원문 그대로 유지하고 번역하지 마세요. "
        f"{output_language_rule} "
        f"{followup_policy} "
        f"{difficulty_followup_rule} "
        'JSON만 반환: {"followup":"<꼬리질문>","followup_question_type":"<evidence|counterexample|application|definition>",'
        '"followup_focus":"<평가 초점>","followup_expected_answer_points":["<요소1>","<요소2>"],'
        '"followup_speech_term_aliases":[{"canonical":"<원문 영문 용어>",'
        '"aliases":["<한글 발음 표기>"]}]}. '
    )
    if not has_meaningful_gap:
        gap_context = "(구체 보완점 없음)"
    elif req.language == "en":
        gap_context = (
            "(The Korean evaluation text is intentionally omitted. "
            "Use only the English follow-up focus below.)"
        )
    elif req.difficulty == "medium":
        gap_context = "(보통 난이도에서는 선택된 단일 보완점만 사용)"
    else:
        gap_context = raw_gap
    strengths_context = (
        "(Korean evaluation text omitted)"
        if req.language == "en"
        else str(evaluation_data.get("strengths", "")).strip()
    )
    user = (
        f"[기본 질문]\n{req.question}\n\n"
        f"[학생 답변]\n{req.answer}\n\n"
        f"[평가 강점]\n{strengths_context}\n\n"
        f"[평가 보완점]\n{gap_context}\n\n"
        f"[후속 질문 핵심]\n{gap_focus or '(구체 보완점 없음)'}\n\n"
        f"[질문 초점]\n{req.question_focus}\n\n"
        f"[관련 발표 자료]\n{slide_context}\n\n"
        "후속 질문 핵심이 있으면 그 개념을 원질문이나 발표 자료와 "
        "자연스럽게 연결해 질문하고, 없으면 앞선 답변을 한 단계 심화하세요. "
        "평가 문구나 보완 지시처럼 들리지 않게 작성하세요."
    )

    data: dict = {}
    try:
        data = llm_client.chat_json(
            system,
            user,
            get_model_hint(req.persona_id),
            kind="followup",
        )
    except Exception:  # noqa: BLE001
        logger.exception("LLM follow-up generation failed; deterministic fallback used")

    raw_question = data.get("followup")
    followup = raw_question.strip() if isinstance(raw_question, str) else ""
    if (
        not followup
        or (
            req.language == "en"
            and _contains_hangul(followup)
        )
        or _is_duplicate_question(
            followup,
            [req.question, req.root_question or ""],
            threshold=0.82,
        )
        or (
            gap_focus
            and not _question_addresses_gap(
                followup,
                gap_focus,
            )
        )
        or (
            req.difficulty == "medium"
            and _is_compound_medium_followup(followup)
        )
    ):
        followup = fallback_question

    if _is_duplicate_question(
        followup,
        [req.question, req.root_question or ""],
        threshold=0.88,
    ):
        return None

    allowed_followup_types = get_allowed_question_types(
        req.persona_id,
        req.difficulty,
    )
    followup_type = _parse_question_type(
        data.get("followup_question_type"),
        fallback_type,
    )
    if followup_type not in allowed_followup_types:
        followup_type = (
            fallback_type
            if fallback_type in allowed_followup_types
            else allowed_followup_types[0]
        )
    if req.difficulty == "medium":
        # 보통 난이도 단일 초점 계약 고정
        followup_focus = fallback_focus
        followup_points = fallback_points[:1]
    else:
        followup_focus_raw = data.get("followup_focus")
        followup_focus = (
            followup_focus_raw.strip()
            if isinstance(followup_focus_raw, str)
            and followup_focus_raw.strip()
            else fallback_focus
        )
        followup_points = _parse_string_list(
            data.get("followup_expected_answer_points"),
            limit=3,
        ) or fallback_points
        if req.language == "en" and (
            _contains_hangul(followup_focus)
            or any(_contains_hangul(point) for point in followup_points)
        ):
            followup_focus = fallback_focus
            followup_points = fallback_points

    followup_alias_source = "\n".join(
        [
            followup,
            *[slide.text for slide in selected_slides[:3]],
        ]
    )
    followup_speech_term_aliases = (
        []
        if req.language == "en"
        else _parse_speech_term_aliases(
            data.get("followup_speech_term_aliases"),
            source_text=followup_alias_source,
        )
    )

    return (
        followup,
        followup_type,
        followup_focus,
        followup_points,
        followup_speech_term_aliases,
    )


def _fallback_substantive_evaluation(
    req: EvaluateRequest,
) -> dict:
    """내용이 있는 답변을 모델이 무응답으로 오분류했을 때의 최소 평가."""
    return {
        "answer_status": "answered",
        "verdict": "부족",
        "strengths": "질문에 답하려고 관련 개념을 설명했습니다.",
        "gaps": (
            "답변은 제출했지만 질문에서 요구한 핵심과 직접 연결되는 내용을 "
            "확인하기 어렵습니다."
        ),
        "expected_point_assessments": [
            {
                "point_index": index,
                "covered": False,
                "answer_evidence": "",
            }
            for index, point in enumerate(req.expected_answer_points[:3])
            if point.strip()
        ],
        "rubric": {
            "직접성": "부족",
            "근거": "부족",
            "논리": "부족",
        },
    }


def _classify_no_answer_with_llm(
    req: EvaluateRequest,
) -> Optional[bool]:
    """정오와 무관하게 실제 답변 시도 여부를 의미 단위로 판별합니다."""
    system = (
        "You classify the communicative intent of a presentation Q&A response. "
        "Judge meaning, not exact wording, spelling, grammar, language, or answer correctness. "
        "Use no_answer only when the speaker solely communicates inability, lack of knowledge, "
        "or refusal and provides no factual claim, reasoning, mechanism, example, or attempted "
        "answer. Use substantive_attempt whenever any answer content is attempted, even if it is "
        "incorrect, incomplete, off-topic, hedged, or distorted by speech recognition. "
        'Return JSON only: {"classification":"no_answer|substantive_attempt"}.'
    )
    user = (
        f"[Question]\n{req.question[:700]}\n\n"
        f"[Response]\n{req.answer[:1800]}"
    )
    try:
        data = llm_client.chat_json(
            system,
            user,
            get_model_hint(req.persona_id),
            kind="evaluate",
        )
    except Exception:  # noqa: BLE001
        logger.exception("No-answer intent classification failed")
        return None

    classification = str(data.get("classification", "")).strip().lower()
    if classification == "no_answer":
        return True
    if classification == "substantive_attempt":
        return False

    logger.warning(
        "Unexpected no-answer classification: %r",
        classification,
    )
    return None


def evaluate_answer(req: EvaluateRequest) -> EvaluateResponse:
    current_role = "retry" if req.is_unknown_retry else req.question_role

    persona = get_persona(req.persona_id)
    persona_system = (
        persona["system"]
        + get_field_hint(req.field)
        + get_question_policy_prompt(
            req.persona_id,
            req.difficulty,
        )
        + get_source_term_preservation(req.language)
    )
    prompt_slides = material_context.build_prompt_slides(req.script, req.slides)
    system, user = prompts.build_evaluate_prompt(
        persona_system=persona_system,
        script=material_context.compact_script(req.script),
        slides=prompt_slides,
        question=req.question,
        answer=req.answer,
        term_hints=req.term_hints,
        difficulty=req.difficulty,
        root_question=req.root_question,
        root_question_type=req.root_question_type,
        question_type=req.question_type,
        question_focus=req.question_focus,
        context_slides=req.context_slides,
        expected_answer_points=req.expected_answer_points,
        language=req.language,
    )
    try:
        data = llm_client.chat_json(
            system,
            user,
            get_model_hint(req.persona_id),
            kind="evaluate",
        )
    except Exception:  # noqa: BLE001
        logger.exception("LLM call failed in /api/evaluate")
        raise HTTPException(
            status_code=502,
            detail="AI 평가 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
        )

    # 모델이 unknown으로 본 답변만 별도의 의미 판정으로 확인합니다.
    # 표현 목록 없이 실제 답변 시도와 명시적 답변 포기를 구분합니다.
    model_status = str(data.get("answer_status", "")).strip().lower()
    recovered_substantive_unknown = False
    if model_status == "unknown":
        no_answer = _classify_no_answer_with_llm(req)
        if no_answer is not False:
            if current_role == "retry":
                return _build_unknown_closure(req)
            return _build_unknown_retry(req)

        recovered_substantive_unknown = True
        reinforced_system = (
            system
            + "\n\n[답변 상태 강제 규칙]\n"
            "학생은 내용이 있는 답변을 제출했습니다. 정답과 다르거나 질문의 주제에서 "
            "벗어났더라도 answer_status는 반드시 answered입니다. 그런 경우 verdict를 "
            "'부족'으로 두고, strengths에는 실제로 시도한 부분만, gaps에는 질문과 "
            "어긋난 핵심을 구체적으로 한국어로 설명하세요. unknown을 반환하지 마세요."
        )
        try:
            data = llm_client.chat_json(
                reinforced_system,
                user,
                get_model_hint(req.persona_id),
                kind="evaluate",
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Substantive answer re-evaluation failed; fallback used"
            )
            data = _fallback_substantive_evaluation(req)

        if str(data.get("answer_status", "")).strip().lower() == "unknown":
            data = _fallback_substantive_evaluation(req)

    data = _audit_uncovered_expected_points(req, data)
    data = _normalize_semantic_consistency(req, data)
    data = _normalize_rubric_consistency(req, data)
    concept_explanation: Optional[EvaluateResponse] = None
    if (
        recovered_substantive_unknown
        and current_role == "retry"
        and str(data.get("verdict", "")).strip() != "충분"
    ):
        concept_explanation = _build_unknown_closure(req)
    response_kwargs = dict(
        answer_status="answered",
        verdict=str(data.get("verdict", "")).strip(),
        strengths=str(data.get("strengths", "")).strip(),
        gaps=str(data.get("gaps", "")).strip(),
        supplement=(
            concept_explanation.supplement
            if concept_explanation
            else None
        ),
        related_slides=(
            concept_explanation.related_slides
            if concept_explanation
            else []
        ),
        rubric=_parse_rubric(data.get("rubric")),
    )

    if recovered_substantive_unknown and current_role == "retry":
        return EvaluateResponse(
            **response_kwargs,
            next_action=_next_action_after_current_question(req),
        )

    # 꼬리질문 답변 뒤에는 추가 꼬리질문 금지
    if current_role == "followup":
        return EvaluateResponse(
            **response_kwargs,
            next_action=_next_action_after_current_question(req),
        )

    # 난이도와 평가 축에 따른 정상 꼬리질문 사용 결정
    if current_role in {"root", "retry"} and _should_ask_followup(
        req,
        response_kwargs["rubric"],
        response_kwargs["gaps"],
    ):
        followup_contract = _build_followup(req, data)
        if followup_contract is not None:
            (
                followup,
                followup_type,
                followup_focus,
                followup_points,
                followup_speech_term_aliases,
            ) = followup_contract
            return EvaluateResponse(
                **response_kwargs,
                followup=followup,
                followup_question_type=followup_type,
                followup_focus=followup_focus,
                followup_expected_answer_points=followup_points,
                followup_speech_term_aliases=followup_speech_term_aliases,
                next_action="ask_followup",
            )

    if current_role in {"root", "retry"}:
        return EvaluateResponse(
            **response_kwargs,
            next_action=_next_action_after_current_question(req),
        )

    return EvaluateResponse(
        **response_kwargs,
        next_action="finish",
    )
