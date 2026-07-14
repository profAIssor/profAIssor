"""Pydantic request/response models for the sparring API."""
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field

Difficulty = Literal["easy", "medium", "hard"]
AcademicField = Literal["engineering", "humanities", "natural"]


class Slide(BaseModel):
    index: int
    text: str


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
    answer: str
    turn: int = 0
    max_turns: int = Field(default=2, ge=0, le=5)
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
