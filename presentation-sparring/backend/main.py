"""FastAPI app: CORS + 3 routes (questions / evaluate / report)."""
import logging
import math
import os
import re
from difflib import SequenceMatcher
from typing import Dict, List

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import llm_client
import material_context
import pdf_extract
import ppt_extract
import prompts
from personas import (
    get_field_hint,
    get_model_hint,
    get_persona,
    get_question_type_priority,
)
from schemas import (
    EvaluateRequest,
    EvaluateResponse,
    QuestionRequest,
    QuestionResponse,
    QuestionType,
    ReportRequest,
    ReportResponse,
    Revision,
    Slide,
    SlideCoverage,
    SlideExtractResponse,
)

app = FastAPI(title="Presentation Sparring API")

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
_EXTRA_ORIGINS = [o.strip() for o in os.getenv("EXTRA_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN, "http://localhost:5173", "http://127.0.0.1:5173", *_EXTRA_ORIGINS],
    allow_origin_regex=r"https://.*\.(netlify\.app|onrender\.com)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok", "provider": llm_client.PROVIDER}


_MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20MB
# Content types tolerated per extension. Browsers/OSes are inconsistent about
# the exact MIME they attach, so "octet-stream"/"" are accepted for both.
_UPLOAD_CONTENT_TYPES = {
    "pptx": {
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/octet-stream",
        "",
    },
    "pdf": {
        "application/pdf",
        "application/x-pdf",
        "application/octet-stream",
        "",
    },
}
_UNSUPPORTED_FORMAT_DETAIL = "지원하지 않는 파일 형식입니다. .pptx 또는 .pdf 파일만 업로드할 수 있습니다."


@app.post("/api/slides/extract", response_model=SlideExtractResponse)
async def extract_slides_endpoint(file: UploadFile = File(...)):
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "ppt":
        raise HTTPException(
            status_code=400,
            detail="구버전 .ppt 파일은 지원하지 않습니다. PowerPoint에서 .pptx로 저장 후 업로드해주세요.",
        )
    if ext not in _UPLOAD_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=_UNSUPPORTED_FORMAT_DETAIL,
        )

    # 브라우저·운영체제별 MIME 차이를 고려한 실제 파일 데이터 읽기
    content = await file.read()

    # 빈 파일 업로드 방지
    if not content:
        raise HTTPException(
            status_code=400,
            detail="업로드된 파일의 내용이 비어 있습니다.",
        )

    # 업로드 파일 크기 제한
    if len(content) > _MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=400,
            detail="파일 크기가 20MB를 초과합니다.",
        )

    extractor = pdf_extract if ext == "pdf" else ppt_extract
    label = "PDF" if ext == "pdf" else "PPT"
    try:
        slides = extractor.extract_slides(content)
    except Exception:  # noqa: BLE001
        logger.exception("%s extraction failed for %s", label, filename)
        raise HTTPException(
            status_code=400,
            detail=f"{label} 파일을 읽는 중 오류가 발생했습니다. 파일이 손상되지 않았는지 확인해주세요.",
        )

    return SlideExtractResponse(slides=slides)


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


def _generate_question_data(
    req: QuestionRequest,
    *,
    persona_system: str,
    question_type_priority: List[str],
) -> dict:
    """슬라이드-대본 내부 매칭과 중복 재생성을 적용한 질문 데이터 생성."""
    prompt_slides = material_context.build_prompt_slides(req.script, req.slides)
    prompt_script = material_context.compact_script(req.script)
    blocked_questions = [
        question.strip()
        for question in req.excluded_questions
        if isinstance(question, str) and question.strip()
    ]
    last_data: dict = {}

    for attempt in range(3):
        system, user = prompts.build_question_prompt(
            persona_system=persona_system,
            script=prompt_script,
            slides=prompt_slides,
            difficulty=req.difficulty,
            question_type_priority=question_type_priority,
            excluded_questions=blocked_questions,
        )
        if attempt > 0:
            user += (
                "\n\n[중복 질문 재생성 지시]\n"
                "직전에 생성한 질문이 이전 질문과 지나치게 유사했습니다. "
                "이미 사용한 질문과 다른 슬라이드, 다른 핵심 쟁점 또는 다른 평가 관점을 "
                "선택해 완전히 새로운 질문을 생성하세요."
            )

        try:
            last_data = llm_client.chat_json(
                system,
                user,
                get_model_hint(req.persona_id),
            )
        except Exception:  # noqa: BLE001
            logger.exception("LLM call failed in /api/questions")
            raise HTTPException(
                status_code=502,
                detail="AI 질문 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
            )

        candidate = str(last_data.get("question", "")).strip()
        if candidate and not _is_duplicate_question(candidate, blocked_questions):
            return last_data
        if candidate:
            blocked_questions.append(candidate)

    raise HTTPException(
        status_code=502,
        detail="AI가 이전 질문과 다른 질문을 생성하지 못했습니다. 잠시 후 다시 시도해주세요.",
    )


@app.post("/api/questions", response_model=QuestionResponse)
def questions(req: QuestionRequest):
    persona = get_persona(req.persona_id)
    persona_system = persona["system"] + get_field_hint(req.field)
    question_type_priority = list(get_question_type_priority(req.persona_id))
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
    question_type = _parse_question_type(
        data.get("question_type"),
        question_type_priority[0],
    )

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

    return QuestionResponse(
        question=question,
        question_type=question_type,
        targets_slide=targets,
        question_focus=question_focus or question[:160],
        context_slides=context_slides,
        expected_answer_points=expected_answer_points,
    )


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


_NO_ANSWER_PATTERN = re.compile(
    r"^(?:(?:잘|정확히|아직)\s*)?"
    r"(?:모르겠습니다|모르겠어요|모르겠네요|모릅니다|모르겠다|"
    r"기억(?:이\s*)?나지\s*않습니다|생각(?:이\s*)?나지\s*않습니다|"
    r"답변하기\s*어렵습니다|확인해\s*봐야\s*합니다|검색해\s*봐야\s*합니다)"
    r"(?:[\s,.!?…]*(?:먼저\s*)?(?:알려|설명해)\s*주(?:시)?겠습니까|"
    r"[\s,.!?…]*(?:알려|설명해)\s*주세요)?[\s.!?…]*$",
    re.IGNORECASE,
)


def _is_no_answer(answer: str) -> bool:
    """명시적인 답변 불가 표현만 보수적으로 감지합니다."""
    normalized = re.sub(r"\s+", " ", answer.strip())
    if not normalized or len(normalized) > 100:
        return False

    compact = re.sub(r"[\s,.!?…]", "", normalized.lower())
    if compact in {
        "모름",
        "잘모름",
        "모르겠습니다",
        "잘모르겠습니다",
        "모르겠어요",
        "잘모르겠어요",
        "모릅니다",
        "idontknow",
    }:
        return True

    return bool(_NO_ANSWER_PATTERN.fullmatch(normalized))


def _next_action_after_current_question(req: EvaluateRequest) -> str:
    """현재 질문 슬롯 종료 뒤 다음 기본 질문 또는 전체 종료 결정."""
    return "move_to_new_root" if req.turn < req.max_turns else "finish"


def _fallback_supplement(question_focus: str, current_type: QuestionType) -> str:
    """모델 보충 설명 누락 시 사용할 사고 방향 안내."""
    focus = re.sub(r"\s+", " ", question_focus.strip())[:120]
    subject = focus or "현재 질문의 핵심 개념"
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
) -> tuple[str, str, List[str]]:
    """현재 질문의 사고 단계를 한 단계 낮춘 재질문 계약 생성."""
    focus = re.sub(r"\s+", " ", question_focus.strip())[:120]
    subject = focus or "현재 질문의 핵심 내용"
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

    system = (
        "당신은 발표 질의응답 연습을 돕는 평가자입니다. "
        "학생이 현재 질문에 답하지 못했으므로 질문 횟수를 차감하지 않는 재도전 기회를 한 번 제공합니다. "
        "학생이 입력한 무응답 문장은 제공되지 않으며 이전 답변을 추론하거나 언급해서는 안 됩니다. "
        "supplement에는 정답 전체를 말하지 말고, 답을 유추하는 데 필요한 전제·비교·인과관계를 2~3문장으로 설명하세요. "
        "retry_question은 현재 질문을 짧게 바꿔 반복하지 말고, 답변에 필요한 사고 과정의 바로 앞 단계 하나만 물으세요. "
        "하나의 요구만 포함하고, 발표 자료 안에서 답을 추론할 수 있어야 합니다. "
        "비정의형 질문을 단순한 용어 정의 질문으로 바꾸지 마세요. "
        "retry_focus와 retry_expected_answer_points는 재질문 자체만 평가할 수 있도록 새로 작성하세요. "
        'JSON만 반환: {"supplement":"<사고 지원 설명>","retry_question":"<재질문>",'
        '"retry_focus":"<재질문의 평가 초점>","retry_expected_answer_points":["<요소1>","<요소2>"],'
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
    )
    supplement_raw = data.get("supplement")
    supplement = (
        supplement_raw.strip()
        if isinstance(supplement_raw, str) and supplement_raw.strip()
        else _fallback_supplement(focus, current_type)
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
        next_action="retry_after_unknown",
        rubric={},
    )


def _fallback_required_followup(
    question_focus: str,
    current_type: QuestionType,
) -> tuple[str, QuestionType, str, List[str]]:
    """정상 답변 이후 심화·확장용 꼬리질문 계약 생성."""
    focus = re.sub(r"\s+", " ", question_focus.strip())[:120]
    subject = focus or "앞선 답변의 핵심 내용"
    next_type = _TYPE_TRANSITIONS[current_type]
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
) -> tuple[str, QuestionType, str, List[str]] | None:
    """기본 질문의 정상 답변을 심화·확장하는 꼬리질문 생성."""
    current_type = req.question_type or req.root_question_type or "definition"
    fallback_question, fallback_type, fallback_focus, fallback_points = (
        _fallback_required_followup(req.question_focus, current_type)
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

    system = (
        "당신은 발표 질의응답의 꼬리질문을 만드는 평가자입니다. "
        "학생은 앞선 기본 질문에 내용 있는 답변을 했습니다. "
        "앞선 질문을 다시 말하거나 같은 정의를 반복해서 묻지 말고, 학생 답변에서 자연스럽게 이어지는 심화 또는 확장 질문 하나를 만드세요. "
        "근거, 조건·한계, 반례, 다른 상황 적용 중 가장 가치 있는 방향 하나만 선택하세요. "
        "질문은 발표 자료와 학생 답변으로 답할 수 있어야 하며, 한 문장에 요구를 하나만 포함하세요. "
        'JSON만 반환: {"followup":"<꼬리질문>","followup_question_type":"<evidence|counterexample|application|definition>",'
        '"followup_focus":"<평가 초점>","followup_expected_answer_points":["<요소1>","<요소2>"]}. '
    )
    user = (
        f"[기본 질문]\n{req.question}\n\n"
        f"[학생 답변]\n{req.answer}\n\n"
        f"[평가 강점]\n{str(evaluation_data.get('strengths', '')).strip()}\n\n"
        f"[평가 보완점]\n{str(evaluation_data.get('gaps', '')).strip()}\n\n"
        f"[질문 초점]\n{req.question_focus}\n\n"
        f"[관련 발표 자료]\n{slide_context}\n\n"
        "앞선 답변을 한 단계 심화하거나 확장하는 꼬리질문 계약을 생성하세요."
    )

    data: dict = {}
    try:
        data = llm_client.chat_json(
            system,
            user,
            get_model_hint(req.persona_id),
        )
    except Exception:  # noqa: BLE001
        logger.exception("LLM follow-up generation failed; deterministic fallback used")

    raw_question = data.get("followup")
    followup = raw_question.strip() if isinstance(raw_question, str) else ""
    if not followup or _is_duplicate_question(
        followup,
        [req.question, req.root_question or ""],
        threshold=0.82,
    ):
        followup = fallback_question

    if _is_duplicate_question(
        followup,
        [req.question, req.root_question or ""],
        threshold=0.88,
    ):
        return None

    followup_type = _parse_question_type(
        data.get("followup_question_type"),
        fallback_type,
    )
    followup_focus_raw = data.get("followup_focus")
    followup_focus = (
        followup_focus_raw.strip()
        if isinstance(followup_focus_raw, str) and followup_focus_raw.strip()
        else fallback_focus
    )
    followup_points = _parse_string_list(
        data.get("followup_expected_answer_points"),
        limit=3,
    ) or fallback_points
    return followup, followup_type, followup_focus, followup_points


@app.post("/api/evaluate", response_model=EvaluateResponse)
def evaluate(req: EvaluateRequest):
    current_role = "retry" if req.is_unknown_retry else req.question_role
    no_answer = _is_no_answer(req.answer)

    # 무응답 재질문의 두 번째 무응답 종료
    if current_role == "retry" and no_answer:
        return EvaluateResponse(
            answer_status="unknown",
            verdict="확인 필요",
            strengths="",
            gaps="재질문에도 답변하지 못해 현재 질문은 여기까지 진행합니다.",
            next_action=_next_action_after_current_question(req),
            rubric={},
        )

    # 기본 질문 또는 꼬리질문의 최초 무응답 처리
    if no_answer:
        return _build_unknown_retry(req)

    persona = get_persona(req.persona_id)
    persona_system = persona["system"] + get_field_hint(req.field)
    prompt_slides = material_context.build_prompt_slides(req.script, req.slides)
    system, user = prompts.build_evaluate_prompt(
        persona_system=persona_system,
        script=material_context.compact_script(req.script),
        slides=prompt_slides,
        question=req.question,
        answer=req.answer,
        turn=req.turn,
        max_turns=req.max_turns,
        term_hints=req.term_hints,
        difficulty=req.difficulty,
        root_question=req.root_question,
        root_question_type=req.root_question_type,
        question_type=req.question_type,
        question_focus=req.question_focus,
        context_slides=req.context_slides,
        expected_answer_points=req.expected_answer_points,
        is_no_answer=False,
    )
    try:
        data = llm_client.chat_json(system, user, get_model_hint(req.persona_id))
    except Exception:  # noqa: BLE001
        logger.exception("LLM call failed in /api/evaluate")
        raise HTTPException(
            status_code=502,
            detail="AI 평가 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
        )

    # 정규식에서 놓친 무응답 뉘앙스의 모델 보조 판정
    model_status = str(data.get("answer_status", "")).strip().lower()
    if model_status == "unknown":
        if current_role == "retry":
            return EvaluateResponse(
                answer_status="unknown",
                verdict="확인 필요",
                strengths="",
                gaps="재질문에도 답변하지 못해 현재 질문은 여기까지 진행합니다.",
                next_action=_next_action_after_current_question(req),
                rubric={},
            )
        return _build_unknown_retry(req)

    response_kwargs = dict(
        answer_status="answered",
        verdict=str(data.get("verdict", "")).strip(),
        strengths=str(data.get("strengths", "")).strip(),
        gaps=str(data.get("gaps", "")).strip(),
        supplement=None,
        related_slides=[],
        rubric=_parse_rubric(data.get("rubric")),
    )

    # 무응답 재질문 또는 꼬리질문 답변 뒤 추가 꼬리질문 금지
    if current_role in {"retry", "followup"}:
        return EvaluateResponse(
            **response_kwargs,
            next_action=_next_action_after_current_question(req),
        )

    # 기본 질문 답변 뒤 남은 질문 슬롯이 있을 때만 꼬리질문 생성
    if req.turn < req.max_turns:
        followup_contract = _build_followup(req, data)
        if followup_contract is not None:
            followup, followup_type, followup_focus, followup_points = followup_contract
            return EvaluateResponse(
                **response_kwargs,
                followup=followup,
                followup_question_type=followup_type,
                followup_focus=followup_focus,
                followup_expected_answer_points=followup_points,
                next_action="ask_followup",
            )
        return EvaluateResponse(
            **response_kwargs,
            next_action="move_to_new_root",
        )

    return EvaluateResponse(
        **response_kwargs,
        next_action="finish",
    )

# ------------------------------------------------------------ report helpers
_FILLER_PATTERN = re.compile(
    r"(?<![가-힣])(어+|음+|그+|저기|뭐|뭔가|약간|이제|막|좀)(?![가-힣])"
)
# Korean particles / trivial tokens to ignore when extracting slide keywords.
_STOPWORDS = {
    "그리고", "그러나", "하지만", "또한", "때문", "위해", "대한", "통해", "있는", "있다",
    "합니다", "입니다", "이다", "및", "등", "the", "and", "for", "with", "this", "that",
}


def _count_fillers(text: str) -> int:
    return len(_FILLER_PATTERN.findall(text))


def _word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def _keywords(text: str) -> List[str]:
    """Extract candidate key terms (>=2 char alnum/Hangul tokens).

    Pure-digit tokens (slide page numbers like "02", "10") are never
    meaningful content, so they're dropped unconditionally.
    """
    tokens = re.findall(r"[A-Za-z0-9가-힣]{2,}", text)
    out = []
    for t in tokens:
        if t.isdigit():
            continue
        if t.lower() in _STOPWORDS:
            continue
        out.append(t)
    return out


def _boilerplate_tokens(slides: List[Slide]) -> set:
    """Tokens repeated across most slides are deck-wide template chrome
    (running headers, section labels like "KEY FINDING") rather than
    slide-specific content, and shouldn't be checked for per-slide coverage.

    Only kicks in for decks with enough slides to make "most slides" a
    meaningful signal; small decks skip this entirely.
    """
    if len(slides) < 4:
        return set()
    doc_freq: Dict[str, int] = {}
    for slide in slides:
        for kw in {k.lower() for k in _keywords(slide.text)}:
            doc_freq[kw] = doc_freq.get(kw, 0) + 1
    threshold = max(3, math.ceil(len(slides) / 2))
    return {kw for kw, freq in doc_freq.items() if freq >= threshold}


# Percentages, decimals, and multi-digit numbers — the data points an
# audience most notices when they go unmentioned. Bare single digits
# (often list/page markers) are excluded to avoid noise.
_FIGURE_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?%?")


def _figures(text: str) -> List[str]:
    """Extract salient numeric figures from slide text.

    Keeps percentages and decimals, and multi-digit integers that don't look
    like page/section markers (a leading zero — "02", "07" — is treated as a
    marker and dropped).
    """
    out = []
    for raw in _FIGURE_PATTERN.findall(text):
        fig = raw.strip(",")
        core = fig.rstrip("%").replace(",", "")
        if not core:
            continue
        if "%" in fig or "." in core:
            out.append(fig)
        elif len(core) >= 2 and not core.startswith("0"):
            out.append(fig)
    return out


def _figure_rank(fig: str) -> int:
    """Order figures by how likely they are the slide's headline number:
    percentages first, then decimals, then plain counts, with year-like
    4-digit numbers (1900–2099) pushed last so "45%" wins over "2023"."""
    if "%" in fig:
        return 0
    if "." in fig:
        return 1
    core = fig.replace(",", "")
    if len(core) == 4 and core.isdigit() and 1900 <= int(core) <= 2099:
        return 3
    return 2


def _fallback_coverage(slide: Slide, script: str, boilerplate: set) -> SlideCoverage:
    """Deterministic keyword-overlap coverage when the LLM didn't judge a slide.

    A slide is 'covered' if a reasonable share of its key terms appear in the
    spoken script. Otherwise the missing point names the missing category —
    a key figure (수치) when a slide number/percent went unspoken, else a key
    term (용어) — so the feedback points at something concrete.
    """
    kws = [k for k in _keywords(slide.text) if k.lower() not in boilerplate]
    if not kws:
        return SlideCoverage(index=slide.index, covered=True, missing_point=None)
    script_low = script.lower()
    missing = [k for k in kws if k.lower() not in script_low]
    covered_ratio = 1 - (len(missing) / len(kws))
    covered = covered_ratio >= 0.5 and len(missing) < len(kws)
    missing_point = None
    if not covered:
        script_digits = re.sub(r"[,\s]", "", script)
        missing_figs = [
            f for f in _figures(slide.text) if f.rstrip("%").replace(",", "") not in script_digits
        ]
        if missing_figs:
            missing_figs.sort(key=_figure_rank)
            missing_point = f"핵심 수치({missing_figs[0]})가 대본에서 언급되지 않았습니다."
        else:
            example = ", ".join(dict.fromkeys(missing))[:60]
            missing_point = f"핵심 용어({example})가 대본에서 언급되지 않았습니다."
    return SlideCoverage(index=slide.index, covered=covered, missing_point=missing_point)


_VALID_ACTION_TYPES = {
    "sentence_split",
    "signal_phrase",
    "emphasis_shift",
    "term_explanation",
    "other",
}


def _parse_revisions(raw, *, valid_slide_indices: set[int], limit: int = 4) -> List[Revision]:
    """LLM이 반환한 revisions 배열을 검증하고 최대 limit개만 남김

    observation/impact/action/example 중 하나라도 비어 있으면 그 항목은
    실행 가능한 코칭으로 보기 어려우므로 통째로 제외
    """
    if not isinstance(raw, list):
        return []

    result: List[Revision] = []

    for item in raw:
        if not isinstance(item, dict):
            continue

        observation = str(item.get("observation", "")).strip()
        impact = str(item.get("impact", "")).strip()
        action = str(item.get("action", "")).strip()
        example = str(item.get("example", "")).strip()

        if not (observation and impact and action and example):
            continue

        action_type = item.get("action_type")
        if action_type not in _VALID_ACTION_TYPES:
            action_type = "other"

        slide_index = item.get("slide_index")
        if isinstance(slide_index, str) and slide_index.strip().isdigit():
            slide_index = int(slide_index.strip())
        if not isinstance(slide_index, int) or slide_index not in valid_slide_indices:
            slide_index = None

        result.append(
            Revision(
                slide_index=slide_index,
                observation=observation[:300],
                impact=impact[:300],
                action_type=action_type,
                action=action[:300],
                example=example[:400],
            )
        )

        if len(result) >= limit:
            break

    return result


@app.post("/api/report", response_model=ReportResponse)
def report(req: ReportRequest):
    system, user = prompts.build_report_prompt(req.script, req.slides, req.transcript)
    try:
        data = llm_client.chat_json(system, user)
    except Exception:  # noqa: BLE001
        logger.exception("LLM call failed in /api/report")
        raise HTTPException(status_code=502, detail="리포트 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")

    # Merge LLM coverage (if any) with a deterministic fallback so EVERY slide
    # is represented and coverage always shows in the report.
    llm_cov: Dict[int, dict] = {}
    for c in data.get("slide_coverage", []) or []:
        try:
            llm_cov[int(c.get("index"))] = c
        except (TypeError, ValueError):
            continue

    coverage: List[SlideCoverage] = []
    if not req.script.strip():
        # No script was provided (slides-only session) — there is nothing to
        # compare slide content against, so don't claim slides are "missing"
        # from a script that never existed.
        coverage = [
            SlideCoverage(index=s.index, covered=True, missing_point=None)
            for s in sorted(req.slides, key=lambda s: s.index)
        ]
    else:
        boilerplate = _boilerplate_tokens(req.slides)
        for slide in sorted(req.slides, key=lambda s: s.index):
            if slide.index in llm_cov:
                c = llm_cov[slide.index]
                covered = bool(c.get("covered", True))
                mp = c.get("missing_point")
                if isinstance(mp, str) and mp.strip().lower() in ("null", "none", ""):
                    mp = None
                coverage.append(
                    SlideCoverage(
                        index=slide.index,
                        covered=covered,
                        missing_point=None if covered else (mp or "핵심 내용이 대본에서 충분히 언급되지 않았습니다."),
                    )
                )
            else:
                coverage.append(_fallback_coverage(slide, req.script, boilerplate))

    valid_slide_indices = {slide.index for slide in req.slides}
    revisions = _parse_revisions(
        data.get("revisions"),
        valid_slide_indices=valid_slide_indices,
    )

    return ReportResponse(
        content_feedback=str(data.get("content_feedback", "")).strip(),
        delivery_feedback=str(data.get("delivery_feedback", "")).strip(),
        response_feedback=str(data.get("response_feedback", "")).strip(),
        slide_coverage=coverage,
        filler_count=_count_fillers(req.script),
        word_count=_word_count(req.script),
        revisions=revisions,
        answer_structure_tip=str(data.get("answer_structure_tip", "")).strip(),
    )