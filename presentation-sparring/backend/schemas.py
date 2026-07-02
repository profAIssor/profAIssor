"""Pydantic request/response models for the sparring API."""
from typing import List, Optional
from pydantic import BaseModel, Field


class Slide(BaseModel):
    index: int
    text: str


# --- /api/questions ---
class QuestionRequest(BaseModel):
    script: str
    slides: List[Slide] = Field(default_factory=list)
    persona_id: str


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


class EvaluateResponse(BaseModel):
    verdict: str
    strengths: str
    gaps: str
    followup: Optional[str] = None


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
