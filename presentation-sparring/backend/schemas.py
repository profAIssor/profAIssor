"""Pydantic request/response models for the sparring API."""
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field

Difficulty = Literal["easy", "medium", "hard"]
AcademicField = Literal["engineering", "humanities", "natural"]


class Slide(BaseModel):
    index: int
    text: str


# --- /api/slides/extract ---
class SlideExtractResponse(BaseModel):
    slides: List[Slide]


# --- /api/questions ---
class QuestionRequest(BaseModel):
    script: str
    slides: List[Slide] = Field(default_factory=list)
    persona_id: str
    difficulty: Difficulty = "medium"
    field: Optional[AcademicField] = None


class QuestionResponse(BaseModel):
    question: str
    targets_slide: Optional[int] = None


# --- /api/evaluate ---
class EvaluateRequest(BaseModel):
    script: str
    persona_id: str
    question: str
    # 현재 persona의 최초 질문. 꼬리질문이 처음 쟁점에서 벗어나지 않도록 유지
    root_question: Optional[str] = None
    answer: str
    turn: int = 0
    # 최초 질문 이후 허용되는 최대 꼬리질문 횟수
    # 기본값은 2회이며, 사용자는 0~3회 범위 내 선택
    max_turns: int = Field(default=2, ge=0, le=3)
    # 최초 질문에서 선택한 난이도를 평가와 꼬리질문에도 유지
    difficulty: Difficulty = "medium"
    field: Optional[AcademicField] = None
    # Presentation-specific terms (from the frontend's script/slide dictionary)
    # so the evaluator can look past likely STT mishearings in `answer`.
    term_hints: List[str] = Field(default_factory=list)


class EvaluateResponse(BaseModel):
    verdict: str
    strengths: str
    gaps: str
    followup: Optional[str] = None
    rubric: Dict[str, str] = Field(default_factory=dict)


# --- /api/report ---
class TranscriptTurn(BaseModel):
    persona_id: str
    question: str
    answer: str
    verdict: str = ""
    gaps: str = ""


class ReportRequest(BaseModel):
    script: str
    slides: List[Slide] = Field(default_factory=list)
    transcript: List[TranscriptTurn] = Field(default_factory=list)
    field: Optional[AcademicField] = None


class SlideCoverage(BaseModel):
    index: int
    covered: bool
    missing_point: Optional[str] = None


class ReportResponse(BaseModel):
    content_feedback: str
    delivery_feedback: str
    response_feedback: str
    slide_coverage: List[SlideCoverage]
    filler_count: int
    word_count: int