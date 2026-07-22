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
import report_prompt
import speech_metrics
from personas import (
    get_allowed_question_types,
    get_field_hint,
    get_model_hint,
    get_persona,
    get_question_policy_prompt,
    get_question_type_priority,
)
from schemas import (
    AnswerCoaching,
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

_SOURCE_TERM_PRESERVATION = (
    "\n\n[원문 용어 보존]\n"
    "슬라이드나 대본에 영어로 적힌 기술 용어, 프로토콜명, 모드명, "
    "알고리즘명, API·표준 명칭, 약어, 코드, 수식은 원문 철자와 "
    "대소문자를 그대로 유지하세요. 한국어 번역어·음역어·의역어로 "
    "바꾸지 마세요. 질문 문장 전체는 한국어 존댓말로 작성하되 "
    "핵심 영문 용어는 슬라이드 원문 그대로 사용하세요. "
    "question_focus, expected_answer_points, supplement, retry_question, "
    "followup에도 같은 규칙을 적용하세요."
)


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
    candidates: List[tuple[float, dict]] = []
    rejected_target_slides: set[int] = set()

    duplicate_threshold = {
        "easy": 0.62,
        "medium": 0.68,
        "hard": 0.74,
    }.get(req.difficulty, 0.68)

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
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "LLM call failed in /api/questions"
            )
            # 이전 시도에서 유효한 후보가 있으면 네트워크 오류 때문에
            # 전체 질문 흐름을 중단하지 않고 가장 덜 유사한 후보 사용
            if candidates:
                candidates.sort(key=lambda item: item[0])
                logger.warning(
                    "Question generation call failed; least similar candidate used: similarity=%.3f",
                    candidates[0][0],
                )
                return candidates[0][1]
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
        candidates.append((similarity, data))

        target_slide = data.get("targets_slide")
        if (
            isinstance(target_slide, str)
            and target_slide.strip().isdigit()
        ):
            target_slide = int(target_slide.strip())
        if isinstance(target_slide, int):
            rejected_target_slides.add(target_slide)

        if similarity < duplicate_threshold:
            return data

        # 다음 재생성 프롬프트에만 탈락 초안 추가
        prompt_blocked_questions.append(candidate)

    if candidates:
        candidates.sort(key=lambda item: item[0])
        best_similarity, best_data = candidates[0]
        best_question = str(
            best_data.get("question", "")
        ).strip()

        # 완전 동일 질문만 아니면 502 대신 가장 덜 유사한 후보로 계속 진행
        if (
            best_question
            and best_similarity < 0.96
            and not any(
                _normalize_question_text(best_question)
                == _normalize_question_text(previous)
                for previous in historical_questions
            )
        ):
            logger.warning(
                "Strict duplicate threshold not met; least similar candidate used: difficulty=%s similarity=%.3f question=%s",
                req.difficulty,
                best_similarity,
                best_question[:160],
            )
            return best_data

    raise HTTPException(
        status_code=502,
        detail=(
            "AI가 유효한 새 질문을 생성하지 못했습니다. "
            "같은 평가자로 다시 시작하거나 질문 횟수를 줄여주세요."
        ),
    )


@app.post("/api/questions", response_model=QuestionResponse)
def questions(req: QuestionRequest):
    persona = get_persona(req.persona_id)
    persona_system = (
        persona["system"]
        + get_field_hint(req.field)
        + get_question_policy_prompt(
            req.persona_id,
            req.difficulty,
        )
        + _SOURCE_TERM_PRESERVATION
    )
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
        "관련 슬라이드의 영문 기술 용어와 고유 명칭은 원문 그대로 유지하고 번역하지 마세요. "
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
        gaps=(
            "이 질문과 관련된 개념을 발표 전에 다시 학습해 주세요."
        ),
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


def _answer_covers_point(
    answer: str,
    point: str,
) -> float:
    """학생 답변의 기대 요소 포함 비율 계산."""
    point_tokens = _focus_tokens(point)
    if not point_tokens:
        return 0.0

    answer_tokens = _focus_tokens(answer)
    return len(point_tokens & answer_tokens) / len(point_tokens)


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


def _select_single_followup_focus(
    req: EvaluateRequest,
    raw_gap: str,
) -> str:
    """학생 답변에서 누락된 기대 요소 한 가지 선택."""
    expected_candidates = [
        _clean_single_focus(point)
        for point in req.expected_answer_points
        if _clean_single_focus(point)
    ]

    if expected_candidates:
        ranked = sorted(
            expected_candidates,
            key=lambda point: (
                _gap_point_score(raw_gap, point),
                1.0 - _answer_covers_point(req.answer, point),
                len(_focus_tokens(point)),
            ),
            reverse=True,
        )
        best = ranked[0]
        if (
            _gap_point_score(raw_gap, best) > 0
            or _answer_covers_point(req.answer, best) < 0.5
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
    """답변의 가장 중요한 보완점을 우선 확인하는 꼬리질문 생성."""
    current_type = req.question_type or req.root_question_type or "definition"
    raw_gap = str(evaluation_data.get("gaps", "")).strip()
    gap_focus = (
        _select_single_followup_focus(req, raw_gap)
        if req.difficulty == "medium"
        else _extract_gap_focus(raw_gap)
    )

    if _has_meaningful_gap(raw_gap):
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
        f"{followup_policy} "
        f"{difficulty_followup_rule} "
        'JSON만 반환: {"followup":"<꼬리질문>","followup_question_type":"<evidence|counterexample|application|definition>",'
        '"followup_focus":"<평가 초점>","followup_expected_answer_points":["<요소1>","<요소2>"]}. '
    )
    gap_context = (
        "(보통 난이도에서는 선택된 단일 보완점만 사용)"
        if req.difficulty == "medium"
        else raw_gap
    )
    user = (
        f"[기본 질문]\n{req.question}\n\n"
        f"[학생 답변]\n{req.answer}\n\n"
        f"[평가 강점]\n{str(evaluation_data.get('strengths', '')).strip()}\n\n"
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
        )
    except Exception:  # noqa: BLE001
        logger.exception("LLM follow-up generation failed; deterministic fallback used")

    raw_question = data.get("followup")
    followup = raw_question.strip() if isinstance(raw_question, str) else ""
    if (
        not followup
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

    return followup, followup_type, followup_focus, followup_points


@app.post("/api/evaluate", response_model=EvaluateResponse)
def evaluate(req: EvaluateRequest):
    current_role = "retry" if req.is_unknown_retry else req.question_role
    no_answer = _is_no_answer(req.answer)

    # 무응답 재질문의 두 번째 무응답 종료
    if current_role == "retry" and no_answer:
        return _build_unknown_closure(req)

    # 기본 질문 또는 꼬리질문의 최초 무응답 처리
    if no_answer:
        return _build_unknown_retry(req)

    persona = get_persona(req.persona_id)
    persona_system = (
        persona["system"]
        + get_field_hint(req.field)
        + get_question_policy_prompt(
            req.persona_id,
            req.difficulty,
        )
        + _SOURCE_TERM_PRESERVATION
    )
    prompt_slides = material_context.build_prompt_slides(req.script, req.slides)
    system, user = prompts.build_evaluate_prompt(
        persona_system=persona_system,
        script=material_context.compact_script(req.script),
        slides=prompt_slides,
        question=req.question,
        answer=req.answer,
        turn=req.turn,
        # 서버 난이도 라우팅 전담을 위한 평가 LLM 꼬리질문 생성 비활성화
        max_turns=0,
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
            return _build_unknown_closure(req)
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
            ) = followup_contract
            return EvaluateResponse(
                **response_kwargs,
                followup=followup,
                followup_question_type=followup_type,
                followup_focus=followup_focus,
                followup_expected_answer_points=followup_points,
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



_PROHIBITED_SPEECH_INFERENCES = (
    "자신감",
    "긴장",
    "감정 상태",
    "억양",
    "피치",
    "단어별 강세",
)


def _parse_speech_delivery_feedback(
    raw,
    *,
    has_speech_summary: bool,
    fallback: str,
) -> str:
    """LLM 음성 코칭의 허용 범위 검증 및 폴백 적용."""
    if not has_speech_summary:
        return ""

    if not isinstance(raw, str):
        return fallback

    normalized = re.sub(r"\s+", " ", raw).strip()
    if not normalized or normalized.lower() in {
        "null",
        "none",
    }:
        return fallback

    if any(
        prohibited in normalized
        for prohibited in _PROHIBITED_SPEECH_INFERENCES
    ):
        logger.warning(
            "Unsupported speech inference discarded: %s",
            normalized[:200],
        )
        return fallback

    return normalized[:800]


_VALID_ACTION_TYPES = {
    "sentence_split",
    "signal_phrase",
    "emphasis_shift",
    "term_explanation",
    "other",
}


def _normalize_grounding_text(text: str) -> str:
    """대본 근거 비교용 문자 정규화."""
    return re.sub(
        r"[^0-9A-Za-z가-힣]+",
        "",
        text,
    ).lower()


def _grounding_tokens(text: str) -> set[str]:
    """대본 근거 비교용 핵심 토큰 추출."""
    return {
        token.lower()
        for token in re.findall(
            r"[0-9A-Za-z가-힣_+.-]{2,}",
            text,
        )
        if token.lower() not in _STOPWORDS
    }


def _script_sentence_candidates(script: str) -> List[str]:
    """대본을 화면에 그대로 표시할 수 있는 문장 후보로 분리."""
    raw_parts = re.split(
        r"(?<=[.!?。！？])\s+|\n+",
        script.strip(),
    )
    candidates: List[str] = []

    for raw in raw_parts:
        normalized = re.sub(r"\s+", " ", raw).strip()
        if not normalized:
            continue

        if len(normalized) <= 450:
            candidates.append(normalized)
            continue

        words = normalized.split()
        chunk: List[str] = []
        chunk_length = 0
        for word in words:
            next_length = chunk_length + len(word) + (1 if chunk else 0)
            if chunk and next_length > 360:
                candidates.append(" ".join(chunk))
                chunk = [word]
                chunk_length = len(word)
            else:
                chunk.append(word)
                chunk_length = next_length
        if chunk:
            candidates.append(" ".join(chunk))

    return candidates


def _find_grounded_script_sentence(
    observation: str,
    script_sentences: List[str],
) -> str | None:
    """LLM 관찰과 가장 가까운 실제 대본 문장 조회."""
    observation_normalized = _normalize_grounding_text(
        observation
    )
    if len(observation_normalized) < 8:
        return None

    observation_tokens = _grounding_tokens(observation)
    best_sentence: str | None = None
    best_score = 0.0

    for sentence in script_sentences:
        sentence_normalized = _normalize_grounding_text(
            sentence
        )
        if not sentence_normalized:
            continue

        if (
            observation_normalized in sentence_normalized
            or sentence_normalized in observation_normalized
        ):
            return sentence

        sequence_score = SequenceMatcher(
            None,
            observation_normalized,
            sentence_normalized,
        ).ratio()

        sentence_tokens = _grounding_tokens(sentence)
        shared_tokens = observation_tokens & sentence_tokens
        token_score = (
            len(shared_tokens)
            / max(
                1,
                min(
                    len(observation_tokens),
                    len(sentence_tokens),
                ),
            )
        )

        score = max(sequence_score, token_score)
        if score > best_score:
            best_score = score
            best_sentence = sentence

    return best_sentence if best_score >= 0.58 else None


def _parse_revisions(
    raw,
    *,
    script: str,
    valid_slide_indices: set[int],
    limit: int = 4,
) -> List[Revision]:
    """실제 발표 대본에 근거한 수정 제안만 보존."""
    if not isinstance(raw, list) or not script.strip():
        return []

    script_sentences = _script_sentence_candidates(
        script
    )
    if not script_sentences:
        return []

    result: List[Revision] = []

    for item in raw:
        if not isinstance(item, dict):
            continue

        observation = str(
            item.get("observation", "")
        ).strip()
        impact = str(item.get("impact", "")).strip()
        action = str(item.get("action", "")).strip()
        example = str(item.get("example", "")).strip()

        if not (observation and impact and action and example):
            continue

        grounded_sentence = _find_grounded_script_sentence(
            observation,
            script_sentences,
        )
        if grounded_sentence is None:
            logger.warning(
                "Ungrounded script revision discarded: %s",
                observation[:160],
            )
            continue

        grounded_tokens = _grounding_tokens(
            grounded_sentence
        )
        example_tokens = _grounding_tokens(example)
        if (
            grounded_tokens
            and not grounded_tokens & example_tokens
        ):
            logger.warning(
                "Unrelated script revision example discarded: %s",
                example[:160],
            )
            continue

        action_type = item.get("action_type")
        if action_type not in _VALID_ACTION_TYPES:
            action_type = "other"

        slide_index = item.get("slide_index")
        if (
            isinstance(slide_index, str)
            and slide_index.strip().isdigit()
        ):
            slide_index = int(slide_index.strip())
        if (
            not isinstance(slide_index, int)
            or slide_index not in valid_slide_indices
        ):
            slide_index = None

        result.append(
            Revision(
                slide_index=slide_index,
                observation=grounded_sentence[:450],
                impact=impact[:300],
                action_type=action_type,
                action=action[:300],
                example=example[:450],
            )
        )

        if len(result) >= limit:
            break

    return result


def _normalized_optional_text(
    value,
    *,
    limit: int,
) -> str | None:
    """LLM 선택 문자열의 null·빈 값 정규화."""
    if not isinstance(value, str):
        return None

    normalized = re.sub(r"\s+", " ", value).strip()
    if not normalized or normalized.lower() in {
        "null",
        "none",
    }:
        return None
    return normalized[:limit]


def _parse_answer_coaching(
    raw,
    transcript,
) -> List[AnswerCoaching]:
    """모든 평가 축이 우수하지 않은 질문의 참고 답변 연결."""
    raw_by_index: Dict[int, dict] = {}
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue

            index = item.get("turn_index")
            if isinstance(index, str) and index.isdigit():
                index = int(index)
            if isinstance(index, int):
                raw_by_index[index] = item

    result: List[AnswerCoaching] = []

    for index, turn in enumerate(transcript):
        rubric_values = list(turn.rubric.values())
        all_excellent = (
            turn.answer_status == "answered"
            and bool(rubric_values)
            and all(
                value == "우수"
                for value in rubric_values
            )
        )

        # 모든 평가 축이 우수하면 보완 카드 미표시
        if all_excellent:
            continue

        item = raw_by_index.get(index, {})
        reference_answer = _normalized_optional_text(
            item.get("reference_answer"),
            limit=900,
        )

        # 재질문에도 답하지 못한 경우 기존 개념 설명 폴백
        if (
            reference_answer is None
            and turn.final_explanation
        ):
            reference_answer = re.sub(
                r"\s+",
                " ",
                turn.final_explanation,
            ).strip()[:900]

        # 재질문 흐름의 자료 기반 힌트 최후 폴백
        if (
            reference_answer is None
            and turn.retry_question
            and turn.supplement
        ):
            reference_answer = re.sub(
                r"\s+",
                " ",
                turn.supplement,
            ).strip()[:900]

        if reference_answer:
            result.append(
                AnswerCoaching(
                    turn_index=index,
                    reference_answer=reference_answer,
                )
            )

    return result


def _needs_reference_answer(turn) -> bool:
    """별도 참고 답변이 필요한 질문 슬롯 판정."""
    rubric_values = list(turn.rubric.values())
    return not (
        turn.answer_status == "answered"
        and bool(rubric_values)
        and all(
            value == "우수"
            for value in rubric_values
        )
    )


def _missing_reference_indices(
    transcript,
    answer_coaching: List[AnswerCoaching],
) -> List[int]:
    """참고 답변이 필요한데 결과에서 누락된 질문 순번 조회."""
    completed_indices = {
        item.turn_index
        for item in answer_coaching
        if item.reference_answer
    }
    return [
        index
        for index, turn in enumerate(transcript)
        if (
            _needs_reference_answer(turn)
            and index not in completed_indices
        )
    ]


def _format_reference_repair_material(
    req: ReportRequest,
    missing_indices: List[int],
) -> str:
    """누락 질문별 관련 발표 자료의 최소 문맥 구성."""
    prompt_slides = material_context.build_prompt_slides(
        req.script,
        req.slides,
    )
    blocks: List[str] = []

    for index in missing_indices:
        turn = req.transcript[index]
        target_question = (
            turn.retry_question
            if turn.retry_question
            else turn.question
        )
        target_answer = (
            turn.retry_answer
            if turn.retry_question
            else turn.answer
        ) or ""

        selected_slides = material_context.select_context_slides(
            prompt_slides,
            turn.related_slides,
            query=target_question,
        )
        slide_context = "\n".join(
            (
                f"[슬라이드 {slide.index}] "
                f"{slide.text[:1600]}"
            )
            for slide in selected_slides[:3]
        ) or "(관련 슬라이드 없음)"

        rubric_context = ", ".join(
            f"{axis}={value}"
            for axis, value in turn.rubric.items()
        ) or "평가 축 없음"

        blocks.append(
            "\n".join(
                [
                    f"[turn_index={index}]",
                    f"질문: {target_question}",
                    f"학생 답변: {target_answer or '(답변 없음)'}",
                    f"최종 평가: {rubric_context}",
                    f"보완점: {turn.gaps}",
                    "관련 발표 자료:",
                    slide_context,
                ]
            )
        )

    return "\n\n".join(blocks)


def _repair_missing_reference_answers(
    req: ReportRequest,
    answer_coaching: List[AnswerCoaching],
) -> List[AnswerCoaching]:
    """리포트 LLM이 누락한 참고 답변을 한 번의 보완 호출로 생성."""
    missing_indices = _missing_reference_indices(
        req.transcript,
        answer_coaching,
    )
    if not missing_indices:
        return answer_coaching

    logger.warning(
        "Missing reference answers detected: indices=%s",
        missing_indices,
    )

    system = (
        "당신은 발표 질의응답 리포트에서 누락된 참고 답변만 보완합니다. "
        "각 항목의 질문과 발표 자료를 근거로 질문에 직접 답하는 "
        "한국어 1~3문장의 완결된 참고 답변을 작성하세요. "
        "학생 답변을 평가하거나 '부족했다'고 언급하지 마세요. "
        "쉬운 재질문이 제시된 항목은 원질문이 아니라 쉬운 재질문에 답하세요. "
        "발표 자료에 없는 사실을 만들지 마세요. "
        "영문 기술 용어, 고유 명칭, 약어는 자료의 원문 표기를 유지하세요. "
        "입력에 있는 turn_index를 그대로 반환하세요. "
        'JSON만 반환: {"answer_coaching": ['
        '{"turn_index": 0, "reference_answer": "<참고 답변>"}'
        "]}"
    )
    user = (
        "[발표 대본]\n"
        f"{req.script.strip() or '(발표 대본 없음)'}\n\n"
        "[참고 답변이 누락된 질문]\n"
        f"{_format_reference_repair_material(req, missing_indices)}\n\n"
        "모든 turn_index에 대해 reference_answer를 빠짐없이 작성하세요."
    )

    repair_data: dict = {}
    try:
        repair_data = llm_client.chat_json(
            system,
            user,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "Reference answer repair call failed"
        )
        return answer_coaching

    repaired_by_index: Dict[int, str] = {}
    raw_items = repair_data.get("answer_coaching")
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue

            index = item.get("turn_index")
            if isinstance(index, str) and index.isdigit():
                index = int(index)

            if (
                not isinstance(index, int)
                or index not in missing_indices
            ):
                continue

            reference_answer = _normalized_optional_text(
                item.get("reference_answer"),
                limit=900,
            )
            if reference_answer:
                repaired_by_index[index] = reference_answer

    merged = {
        item.turn_index: item
        for item in answer_coaching
        if item.reference_answer
    }
    for index, reference_answer in repaired_by_index.items():
        merged[index] = AnswerCoaching(
            turn_index=index,
            reference_answer=reference_answer,
        )

    remaining = [
        index
        for index in missing_indices
        if index not in merged
    ]
    if remaining:
        logger.warning(
            "Reference answers still missing after repair: indices=%s",
            remaining,
        )

    return [
        merged[index]
        for index in sorted(merged)
    ]



_SCRIPT_MISSING_CONTENT = (
    "발표 대본이 제공되지 않아 발표자가 실제로 전달한 내용의 "
    "구조·근거·누락을 평가하지 못했습니다."
)
_SCRIPT_MISSING_DELIVERY = (
    "발표 대본이 제공되지 않아 문장 명확성, 용어 설명, 설명 순서를 "
    "평가하지 못했습니다. 질의응답 대응은 별도 항목에서 확인해 주세요."
)
_SLIDES_MISSING_CONTENT_NOTICE = (
    "슬라이드가 제공되지 않아 대본과 시각 자료의 일치 여부나 "
    "슬라이드 핵심 누락은 판단하지 못했습니다."
)


def _append_feedback_notice(
    feedback: str,
    notice: str,
) -> str:
    """기존 피드백에 자료 부재 안내 중복 없이 추가."""
    normalized = re.sub(r"\s+", " ", feedback).strip()
    if not normalized:
        return notice
    if notice in normalized:
        return normalized
    return f"{normalized} {notice}"



@app.post("/api/report", response_model=ReportResponse)
def report(req: ReportRequest):
    has_script = bool(req.script.strip())
    has_slides = bool(req.slides)
    coverage_available = has_script and has_slides

    (
        speech_summary,
        deterministic_speech_feedback,
    ) = speech_metrics.build_speech_report(
        req.transcript
    )
    speech_prompt_context = (
        speech_metrics.build_speech_prompt_context(
            speech_summary
        )
    )
    system, user = report_prompt.build_report_prompt(
        req.script,
        req.slides,
        req.transcript,
        speech_context=speech_prompt_context,
    )
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
    if coverage_available:
        boilerplate = _boilerplate_tokens(req.slides)
        for slide in sorted(req.slides, key=lambda s: s.index):
            if slide.index in llm_cov:
                c = llm_cov[slide.index]
                covered = bool(c.get("covered", True))
                mp = c.get("missing_point")
                if (
                    isinstance(mp, str)
                    and mp.strip().lower()
                    in ("null", "none", "")
                ):
                    mp = None
                coverage.append(
                    SlideCoverage(
                        index=slide.index,
                        covered=covered,
                        missing_point=(
                            None
                            if covered
                            else (
                                mp
                                or "핵심 내용이 대본에서 충분히 언급되지 않았습니다."
                            )
                        ),
                    )
                )
            else:
                coverage.append(
                    _fallback_coverage(
                        slide,
                        req.script,
                        boilerplate,
                    )
                )

    valid_slide_indices = {slide.index for slide in req.slides}
    revisions = (
        _parse_revisions(
            data.get("revisions"),
            script=req.script,
            valid_slide_indices=valid_slide_indices,
        )
        if has_script
        else []
    )
    answer_coaching = _parse_answer_coaching(
        data.get("answer_coaching"),
        req.transcript,
    )
    answer_coaching = _repair_missing_reference_answers(
        req,
        answer_coaching,
    )

    speech_delivery_feedback = (
        _parse_speech_delivery_feedback(
            data.get("speech_delivery_feedback"),
            has_speech_summary=speech_summary is not None,
            fallback=deterministic_speech_feedback,
        )
    )

    content_feedback = str(
        data.get("content_feedback", "")
    ).strip()
    delivery_feedback = str(
        data.get("delivery_feedback", "")
    ).strip()
    response_feedback = str(
        data.get("response_feedback", "")
    ).strip()

    if not has_script:
        content_feedback = _SCRIPT_MISSING_CONTENT
        delivery_feedback = _SCRIPT_MISSING_DELIVERY
    elif not has_slides:
        content_feedback = _append_feedback_notice(
            content_feedback,
            _SLIDES_MISSING_CONTENT_NOTICE,
        )

    if not response_feedback:
        response_feedback = (
            "질의응답 기록이 없어 질문 대응을 평가하지 못했습니다."
            if not req.transcript
            else "질문에 대한 직접성과 근거 제시를 다시 확인해 주세요."
        )

    return ReportResponse(
        content_feedback=content_feedback,
        delivery_feedback=delivery_feedback,
        response_feedback=response_feedback,
        slide_coverage=coverage,
        filler_count=(
            speech_summary.recognized_filler_count
            if speech_summary is not None
            else 0
        ),
        filler_count_mode=(
            "recognized_minimum"
            if speech_summary is not None
            else "unavailable"
        ),
        word_count=_word_count(req.script),
        speech_summary=speech_summary,
        speech_delivery_feedback=speech_delivery_feedback,
        revisions=revisions,
        answer_coaching=answer_coaching,
        answer_structure_tip=str(
            data.get("answer_structure_tip", "")
        ).strip(),
        script_available=has_script,
        slides_available=has_slides,
        slide_coverage_available=coverage_available,
    )