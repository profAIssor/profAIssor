"""FastAPI app: CORS + 3 routes (questions / evaluate / report)."""
import logging
import os
import re
from typing import Dict, List

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import llm_client
import prompts
from personas import get_field_hint, get_model_hint, get_persona
from schemas import (
    EvaluateRequest,
    EvaluateResponse,
    QuestionRequest,
    QuestionResponse,
    ReportRequest,
    ReportResponse,
    Slide,
    SlideCoverage,
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


@app.post("/api/questions", response_model=QuestionResponse)
def questions(req: QuestionRequest):
    persona = get_persona(req.persona_id)
    persona_system = persona["system"] + get_field_hint(req.field)
    system, user = prompts.build_question_prompt(
        persona_system, req.script, req.slides, req.difficulty
    )
    try:
        data = llm_client.chat_json(system, user, get_model_hint(req.persona_id))
    except Exception:  # noqa: BLE001
        logger.exception("LLM call failed in /api/questions")
        raise HTTPException(status_code=502, detail="AI 질문 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")
    targets = data.get("targets_slide")
    if isinstance(targets, str) and targets.strip().isdigit():
        targets = int(targets)
    if not isinstance(targets, int):
        targets = None
    return QuestionResponse(question=str(data.get("question", "")).strip(), targets_slide=targets)


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


@app.post("/api/evaluate", response_model=EvaluateResponse)
def evaluate(req: EvaluateRequest):
    persona = get_persona(req.persona_id)
    persona_system = persona["system"] + get_field_hint(req.field)
    system, user = prompts.build_evaluate_prompt(
        persona_system, req.script, req.question, req.answer, req.turn, req.max_turns,
        req.term_hints,
    )
    try:
        data = llm_client.chat_json(system, user, get_model_hint(req.persona_id))
    except Exception:  # noqa: BLE001
        logger.exception("LLM call failed in /api/evaluate")
        raise HTTPException(status_code=502, detail="AI 평가 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")
    followup = data.get("followup")
    if isinstance(followup, str) and followup.strip().lower() in ("null", "none", ""):
        followup = None
    # Hard guard: never allow a followup once turn >= max_turns.
    if req.turn >= req.max_turns:
        followup = None
    return EvaluateResponse(
        verdict=str(data.get("verdict", "")).strip(),
        strengths=str(data.get("strengths", "")).strip(),
        gaps=str(data.get("gaps", "")).strip(),
        followup=followup.strip() if isinstance(followup, str) else None,
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
    """Extract candidate key terms (>=2 char alnum/Hangul tokens)."""
    tokens = re.findall(r"[A-Za-z0-9가-힣]{2,}", text)
    out = []
    for t in tokens:
        if t.lower() in _STOPWORDS:
            continue
        out.append(t)
    return out


def _fallback_coverage(slide: Slide, script: str) -> SlideCoverage:
    """Deterministic keyword-overlap coverage when the LLM didn't judge a slide.

    A slide is 'covered' if a reasonable share of its key terms appear in the
    spoken script. Otherwise report the first missing key term.
    """
    kws = _keywords(slide.text)
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
            coverage.append(_fallback_coverage(slide, req.script))

    return ReportResponse(
        content_feedback=str(data.get("content_feedback", "")).strip(),
        delivery_feedback=str(data.get("delivery_feedback", "")).strip(),
        response_feedback=str(data.get("response_feedback", "")).strip(),
        slide_coverage=coverage,
        filler_count=_count_fillers(req.script),
        word_count=_word_count(req.script),
    )
