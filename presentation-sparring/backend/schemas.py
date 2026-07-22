"""Pydantic request/response models for the sparring API."""

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

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
SpeechInputMode = Literal["speech", "mixed"]
SpeechMetricConfidence = Literal["high", "medium", "low"]
PaceStatus = Literal["slow", "balanced", "fast"]
VolumeVariationStatus = Literal["low", "moderate", "high"]
FillerCountMode = Literal["recognized_minimum", "unavailable", "legacy_script"]


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
class SpeechMetrics(BaseModel):
    """답변 한 건의 브라우저 음성 분석 요약."""

    input_mode: SpeechInputMode
    segment_count: int = Field(ge=1, le=30)
    captured_duration_ms: int = Field(ge=0, le=30 * 60 * 1000)
    voiced_duration_ms: int = Field(ge=0, le=30 * 60 * 1000)
    initial_response_latency_ms: Optional[int] = Field(
        default=None,
        ge=0,
        le=10 * 60 * 1000,
    )
    stt_word_count: int = Field(ge=0, le=10000)
    pace_wpm: Optional[float] = Field(default=None, ge=0, le=1000)
    internal_pause_count: int = Field(ge=0, le=10000)
    long_pause_count: int = Field(ge=0, le=10000)
    longest_pause_ms: Optional[int] = Field(
        default=None,
        ge=0,
        le=30 * 60 * 1000,
    )
    volume_variation_db: Optional[float] = Field(
        default=None,
        ge=0,
        le=120,
    )
    recognized_filler_count: int = Field(ge=0, le=10000)
    filler_measurement: Literal["recognized_minimum"]
    confidence: SpeechMetricConfidence
    confidence_reasons: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_metric_relationships(self):
        """음성 지표 간 기본 관계 검증."""
        if self.voiced_duration_ms > self.captured_duration_ms:
            raise ValueError(
                "voiced_duration_ms는 captured_duration_ms보다 클 수 없습니다."
            )
        if self.long_pause_count > self.internal_pause_count:
            raise ValueError(
                "long_pause_count는 internal_pause_count보다 클 수 없습니다."
            )
        return self


class SpeechSummary(BaseModel):
    """세션 단위 음성 지표 집계."""

    measured_answer_count: int = Field(ge=0)
    reliable_answer_count: int = Field(ge=0)
    total_answer_count: int = Field(ge=0)
    total_voiced_duration_ms: int = Field(ge=0)
    session_pace_wpm: Optional[float] = Field(default=None, ge=0, le=1000)
    pace_status: Optional[PaceStatus] = None
    long_pause_count: int = Field(ge=0)
    longest_pause_ms: Optional[int] = Field(default=None, ge=0)
    recognized_filler_count: int = Field(ge=0)
    filler_measurement: Literal["recognized_minimum"]
    average_initial_latency_ms: Optional[float] = Field(default=None, ge=0)
    volume_variation_db: Optional[float] = Field(default=None, ge=0, le=120)
    volume_variation_status: Optional[VolumeVariationStatus] = None

    @model_validator(mode="after")
    def validate_answer_counts(self):
        """세션 음성 답변 수 관계 검증."""
        if self.reliable_answer_count > self.measured_answer_count:
            raise ValueError(
                "reliable_answer_count는 measured_answer_count보다 클 수 없습니다."
            )
        if self.measured_answer_count > self.total_answer_count:
            raise ValueError(
                "measured_answer_count는 total_answer_count보다 클 수 없습니다."
            )
        return self


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
    speech_metrics: Optional[SpeechMetrics] = None

    # 최초 무응답과 쉬운 재질문을 하나의 질문 슬롯으로 보존
    retry_question: Optional[str] = None
    retry_answer: Optional[str] = None
    retry_speech_metrics: Optional[SpeechMetrics] = None

    # 재질문에도 답하지 못했을 때 제공한 최종 개념 설명
    final_explanation: Optional[str] = None


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


class AnswerCoaching(BaseModel):
    """질문 슬롯별 참고 답변."""

    turn_index: int = Field(ge=0)
    reference_answer: Optional[str] = None


class ReportResponse(BaseModel):
    content_feedback: str
    delivery_feedback: str
    response_feedback: str
    slide_coverage: List[SlideCoverage]
    # 기존 프론트 호환용 필드이며 새 세션에서는 final STT 인식 하한선 사용
    filler_count: int
    filler_count_mode: FillerCountMode = "legacy_script"
    word_count: int
    speech_summary: Optional[SpeechSummary] = None
    speech_delivery_feedback: str = ""
    revisions: List[Revision] = Field(default_factory=list)
    answer_coaching: List[AnswerCoaching] = Field(default_factory=list)
    answer_structure_tip: str = ""

    # 리포트 화면의 자료 유무별 분기 지원
    script_available: bool = True
    slides_available: bool = True
    slide_coverage_available: bool = True