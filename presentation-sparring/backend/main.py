"""FastAPI app: CORS + 3 routes (questions / evaluate / report)."""
import logging
import math
import os
import re
from typing import Dict, List

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import llm_client
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


_MAX_PPT_SIZE = 20 * 1024 * 1024  # 20MB
_PPTX_CONTENT_TYPES = {
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/octet-stream",  # many clients send this generically
    "",
}


@app.post("/api/slides/extract", response_model=SlideExtractResponse)
async def extract_slides_endpoint(file: UploadFile = File(...)):
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "ppt":
        raise HTTPException(
            status_code=400,
            detail="구버전 .ppt 파일은 지원하지 않습니다. PowerPoint에서 .pptx로 저장 후 업로드해주세요.",
        )
    if ext != "pptx":
        raise HTTPException(status_code=400, detail="지원하지 않는 파일 형식입니다. .pptx 파일만 업로드할 수 있습니다.")
    if file.content_type and file.content_type not in _PPTX_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="지원하지 않는 파일 형식입니다. .pptx 파일만 업로드할 수 있습니다.")

    content = await file.read()
    if len(content) > _MAX_PPT_SIZE:
        raise HTTPException(status_code=400, detail="파일 크기가 20MB를 초과합니다.")

    try:
        slides = ppt_extract.extract_slides(content)
    except Exception:  # noqa: BLE001
        logger.exception("PPT extraction failed for %s", filename)
        raise HTTPException(
            status_code=400,
            detail="PPT 파일을 읽는 중 오류가 발생했습니다. 파일이 손상되지 않았는지 확인해주세요.",
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


@app.post("/api/questions", response_model=QuestionResponse)
def questions(req: QuestionRequest):
    persona = get_persona(req.persona_id)
    persona_system = persona["system"] + get_field_hint(req.field)
    question_type_priority = get_question_type_priority(req.persona_id)

    system, user = prompts.build_question_prompt(
        persona_system=persona_system,
        script=req.script,
        slides=req.slides,
        difficulty=req.difficulty,
        question_type_priority=question_type_priority,
        excluded_questions=req.excluded_questions,
    )

    try:
        data = llm_client.chat_json(
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

    valid_slide_indices = {slide.index for slide in req.slides}
    targets = data.get("targets_slide")

    if isinstance(targets, str) and targets.strip().isdigit():
        targets = int(targets)

    if not isinstance(targets, int) or targets not in valid_slide_indices:
        targets = None

    # LLM 응답이 잘못되거나 누락되면 persona의 첫 번째 우선 유형을 사용합니다.
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


def _fallback_supplement(expected_points: List[str]) -> str:
    """LLM 보충 문장이 비어 있을 때 내부 기대 요소로 짧은 힌트를 만듭니다."""
    points = [point.strip() for point in expected_points if point.strip()][:2]
    if points:
        return (
            "핵심 확인 항목은 "
            + ", ".join(points)
            + "입니다. 발표 자료에서 각 항목의 의미와 연결 관계를 다시 정리해 보세요."
        )

    return "질문의 핵심 개념과 비교 기준을 발표 자료에서 다시 확인해 보세요."


def _fallback_unknown_retry(question_focus: str) -> str:
    """LLM 재질문이 비어 있을 때 같은 주제를 더 쉽게 묻는 문장 생성."""
    focus = re.sub(r"\s+", " ", question_focus.strip())[:120]

    if focus:
        return (
            f"힌트를 바탕으로, {focus}에서 가장 기본이 되는 의미나 관계 한 가지만 "
            "말씀해 주실 수 있나요?"
        )

    return (
        "힌트를 바탕으로, 원래 질문과 관련된 가장 기본적인 내용 한 가지만 "
        "말씀해 주실 수 있나요?"
    )


def _fallback_required_followup(
    question_focus: str,
    current_type: QuestionType,
    difficulty: str,
    turn: int,
) -> tuple[str, QuestionType]:
    """남은 정상 꼬리질문 횟수 보장을 위한 대체 질문 생성."""
    focus = re.sub(r"\s+", " ", question_focus.strip())[:120]
    subject = focus or "원래 질문의 핵심 내용"

    # 첫 정상 꼬리질문의 인접 유형 전환
    next_type = current_type
    if turn == 0:
        if difficulty == "easy":
            if current_type == "definition":
                next_type = "application"
        else:
            next_type = _TYPE_TRANSITIONS[current_type]

    templates: Dict[QuestionType, str] = {
        "definition": (
            f"{subject}을 판단할 때 가장 중요한 의미나 구분 기준 한 가지는 무엇인가요?"
        ),
        "evidence": (
            f"{subject}에 관한 방금 답변을 뒷받침하는 자료 속 근거 한 가지는 무엇인가요?"
        ),
        "counterexample": (
            f"{subject}에 관한 설명이 그대로 성립하지 않을 수 있는 자료 속 조건 한 가지는 무엇인가요?"
        ),
        "application": (
            f"{subject}에 관한 방금 설명을 자료 속 다른 예시에 적용하면 어떻게 판단할 수 있나요?"
        ),
    }

    return templates[next_type], next_type


@app.post("/api/evaluate", response_model=EvaluateResponse)
def evaluate(req: EvaluateRequest):
    no_answer = _is_no_answer(req.answer)
    current_type = req.question_type or req.root_question_type or "definition"

    # 쉬운 재질문의 명시적 답변 불가에 대한 LLM 호출 생략
    if req.is_unknown_retry and no_answer:
        followup = None
        followup_question_type = None

        if req.turn < req.max_turns:
            followup, followup_question_type = _fallback_required_followup(
                question_focus=req.question_focus,
                current_type=current_type,
                difficulty=req.difficulty,
                turn=req.turn,
            )

        return EvaluateResponse(
            answer_status="unknown",
            verdict="확인 필요",
            strengths="",
            gaps="쉬운 재질문에도 답변하지 못해 이 질문은 여기까지 진행합니다.",
            supplement=None,
            related_slides=[],
            followup=followup,
            followup_question_type=followup_question_type,
            rubric={},
        )

    persona = get_persona(req.persona_id)
    persona_system = persona["system"] + get_field_hint(req.field)

    system, user = prompts.build_evaluate_prompt(
        persona_system=persona_system,
        script=req.script,
        slides=req.slides,
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
        is_no_answer=no_answer,
    )
    try:
        data = llm_client.chat_json(system, user, get_model_hint(req.persona_id))
    except Exception:  # noqa: BLE001
        logger.exception("LLM call failed in /api/evaluate")
        raise HTTPException(status_code=502, detail="AI 평가 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")

    # LLM도 답변 불가로 판단한 경우를 보조적으로 수용하되,
    # 명시적 표현은 서버 판정을 최종 기준으로 사용합니다.
    model_status = str(data.get("answer_status", "")).strip().lower()
    is_unknown = no_answer or model_status == "unknown"

    valid_slide_indices = {slide.index for slide in req.slides}
    preferred_slide_indices = {
        index for index in req.context_slides if index in valid_slide_indices
    }
    related_valid_values = preferred_slide_indices or valid_slide_indices
    related_slides = _parse_int_list(
        data.get("related_slides"),
        valid_values=related_valid_values,
    )

    supplement_raw = data.get("supplement")
    supplement = supplement_raw.strip() if isinstance(supplement_raw, str) else None
    if supplement and supplement.lower() in ("null", "none"):
        supplement = None

    if is_unknown:
        # 쉬운 재질문에서 재차 감지된 답변 불가의 반복 차단
        if req.is_unknown_retry:
            followup = None
            followup_question_type = None

            if req.turn < req.max_turns:
                followup, followup_question_type = _fallback_required_followup(
                    question_focus=req.question_focus,
                    current_type=current_type,
                    difficulty=req.difficulty,
                    turn=req.turn,
                )

            return EvaluateResponse(
                answer_status="unknown",
                verdict="확인 필요",
                strengths="",
                gaps="쉬운 재질문에도 답변하지 못해 이 질문은 여기까지 진행합니다.",
                supplement=None,
                related_slides=[],
                followup=followup,
                followup_question_type=followup_question_type,
                rubric={},
            )

        # 최초 답변 불가의 힌트 및 쉬운 재질문 반환
        if not related_slides and preferred_slide_indices:
            related_slides = sorted(preferred_slide_indices)[:2]

        model_gaps = str(data.get("gaps", "")).strip()
        retry_question = data.get("followup")
        if (
            isinstance(retry_question, str)
            and retry_question.strip().lower() in ("null", "none", "")
        ):
            retry_question = None

        # 모델 누락 시 동일 주제의 쉬운 재질문 보장
        if not isinstance(retry_question, str):
            retry_question = _fallback_unknown_retry(req.question_focus)

        retry_question_type = _parse_question_type(
            data.get("followup_question_type"),
            "definition",
        )

        return EvaluateResponse(
            answer_status="unknown",
            verdict="확인 필요",
            strengths="",
            gaps=model_gaps or "질문의 핵심 내용을 발표 전에 다시 확인해 보세요.",
            supplement=supplement or _fallback_supplement(req.expected_answer_points),
            related_slides=related_slides,
            followup=retry_question.strip(),
            followup_question_type=retry_question_type,
            rubric={},
        )

    followup = data.get("followup")
    if isinstance(followup, str) and followup.strip().lower() in ("null", "none", ""):
        followup = None

    allowed_types = _allowed_followup_types(
        current_type=current_type,
        difficulty=req.difficulty,
        turn=req.turn,
    )

    followup_question_type = None
    if isinstance(followup, str):
        parsed_followup_type = _parse_question_type(
            data.get("followup_question_type"),
            current_type,
        )
        followup_question_type = (
            parsed_followup_type
            if parsed_followup_type in allowed_types
            else current_type
        )

    # 모델 누락에 대한 정상 꼬리질문 횟수 보장
    if req.turn < req.max_turns and not isinstance(followup, str):
        fallback_followup, fallback_type = _fallback_required_followup(
            question_focus=req.question_focus,
            current_type=current_type,
            difficulty=req.difficulty,
            turn=req.turn,
        )
        followup = fallback_followup
        followup_question_type = (
            fallback_type if fallback_type in allowed_types else current_type
        )

    # 선택한 정상 꼬리질문 횟수 완료 후 종료
    if req.turn >= req.max_turns:
        followup = None
        followup_question_type = None

    return EvaluateResponse(
        answer_status="answered",
        verdict=str(data.get("verdict", "")).strip(),
        strengths=str(data.get("strengths", "")).strip(),
        gaps=str(data.get("gaps", "")).strip(),
        supplement=None,
        related_slides=[],
        followup=followup.strip() if isinstance(followup, str) else None,
        followup_question_type=followup_question_type,
        rubric=_parse_rubric(data.get("rubric")),
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


def _fallback_coverage(slide: Slide, script: str, boilerplate: set) -> SlideCoverage:
    """Deterministic keyword-overlap coverage when the LLM didn't judge a slide.

    A slide is 'covered' if a reasonable share of its key terms appear in the
    spoken script. Otherwise report the first missing key term.
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
        missing_point = (
            f"'{', '.join(dict.fromkeys(missing))[:60]}' 관련 핵심 내용이 대본에서 언급되지 않았습니다."
        )
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