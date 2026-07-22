"""Pydantic request/response models for the sparring API."""

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

Difficulty = Literal["easy", "medium", "hard"]
AcademicField = Literal["engineering", "humanities", "natural"]
QuestionType = Literal[
    "evidence",
    "counterexample",
    "application",
    "definition",
]
AnswerStatus = Literal["answered", "unknown"]
QuestionRole = Literal["root", "followup", "retry"]
EvaluationNextAction = Literal[
    "retry_after_unknown",
    "ask_followup",
    "move_to_new_root",
    "finish",
]


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
    excluded_questions: List[str] = Field(default_factory=list)


class QuestionResponse(BaseModel):
    question: str
    question_type: QuestionType
    targets_slide: Optional[int] = None
    question_focus: str = ""
    context_slides: List[int] = Field(default_factory=list)
    expected_answer_points: List[str] = Field(default_factory=list)


# --- /api/evaluate ---
class EvaluateRequest(BaseModel):
    script: str
    slides: List[Slide] = Field(default_factory=list)
    persona_id: str
    question: str
    root_question: Optional[str] = None
    root_question_type: Optional[QuestionType] = None
    question_type: Optional[QuestionType] = None
    question_role: QuestionRole = "root"
    question_focus: str = ""
    context_slides: List[int] = Field(default_factory=list)
    expected_answer_points: List[str] = Field(default_factory=list)
    answer: str
    # 현재 질문 슬롯의 0부터 시작하는 순번
    turn: int = 0
    # 최초 질문 이후 허용되는 추가 질문 수
    max_turns: int = Field(default=2, ge=0, le=3)
    difficulty: Difficulty = "medium"
    field: Optional[AcademicField] = None
    term_hints: List[str] = Field(default_factory=list)
    # 이전 프론트엔드 요청 호환용 재질문 표시
    is_unknown_retry: bool = False


class EvaluateResponse(BaseModel):
    verdict: str
    strengths: str
    gaps: str
    answer_status: AnswerStatus = "answered"
    rubric: Dict[str, str] = Field(default_factory=dict)
    next_action: EvaluationNextAction = "finish"

    # 정상 답변 뒤 심화·확장 꼬리질문 계약
    followup: Optional[str] = None
    followup_question_type: Optional[QuestionType] = None
    followup_focus: str = ""
    followup_expected_answer_points: List[str] = Field(default_factory=list)

    # 무응답 뒤 질문 수를 차감하지 않는 재질문 계약
    supplement: Optional[str] = None
    related_slides: List[int] = Field(default_factory=list)
    retry_question: Optional[str] = None
    retry_question_type: Optional[QuestionType] = None
    retry_question_focus: str = ""
    retry_expected_answer_points: List[str] = Field(default_factory=list)


# --- /api/report ---
class TranscriptTurn(BaseModel):
    persona_id: str
    question: str
    question_type: Optional[QuestionType] = None
    question_role: Optional[QuestionRole] = None
    answer: str
    verdict: str = ""
    strengths: str = ""
    gaps: str = ""
    answer_status: AnswerStatus = "answered"
    supplement: Optional[str] = None
    related_slides: List[int] = Field(default_factory=list)
    rubric: Dict[str, str] = Field(default_factory=dict)


RevisionActionType = Literal[
    "sentence_split",
    "signal_phrase",
    "emphasis_shift",
    "term_explanation",
    "other",
]


class Revision(BaseModel):
    """관찰→영향→수정 행동→수정 예시 구조의 개별 코칭 항목."""

    slide_index: Optional[int] = None
    observation: str
    impact: str
    action_type: RevisionActionType = "other"
    action: str
    example: str


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
    revisions: List[Revision] = Field(default_factory=list)
    answer_structure_tip: str = ""