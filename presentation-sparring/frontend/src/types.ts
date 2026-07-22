export type PersonaId = 'standard' | 'professor' | 'peer' | 'layperson'
export type Difficulty = 'easy' | 'medium' | 'hard'
export type AcademicField = 'engineering' | 'humanities' | 'natural'
export type QuestionType = 'evidence' | 'counterexample' | 'application' | 'definition'
export type AnswerStatus = 'answered' | 'unknown'
export type QuestionRole = 'root' | 'followup' | 'retry'

/** 평가 직후 프론트엔드에서 실행할 질문 흐름 구분. */
export type EvaluationNextAction =
  | 'retry_after_unknown'
  | 'ask_followup'
  | 'move_to_new_root'
  | 'finish'

export interface Persona {
  id: PersonaId
  name: string
  emoji: string
  blurb: string
}

export interface Slide {
  index: number
  text: string
}

export interface QuestionResponse {
  question: string
  question_type: QuestionType
  targets_slide: number | null
  question_focus: string
  context_slides: number[]
  expected_answer_points: string[]
}

export interface EvaluateResponse {
  verdict: string
  strengths: string
  gaps: string
  answer_status: AnswerStatus
  rubric: Record<string, string>
  next_action: EvaluationNextAction

  followup: string | null
  followup_question_type: QuestionType | null
  followup_focus: string
  followup_expected_answer_points: string[]

  supplement: string | null
  related_slides: number[]
  retry_question: string | null
  retry_question_type: QuestionType | null
  retry_question_focus: string
  retry_expected_answer_points: string[]
}

export interface TranscriptTurn {
  persona_id: string
  question: string
  question_type?: QuestionType
  question_role?: QuestionRole
  answer: string
  verdict: string
  strengths: string
  gaps: string
  answer_status?: AnswerStatus
  supplement?: string | null
  related_slides?: number[]
  rubric: Record<string, string>
}

export interface SlideExtractResponse {
  slides: Slide[]
}

export interface SlideCoverage {
  index: number
  covered: boolean
  missing_point: string | null
}

export type RevisionActionType =
  | 'sentence_split'
  | 'signal_phrase'
  | 'emphasis_shift'
  | 'term_explanation'
  | 'other'

export interface Revision {
  slide_index: number | null
  observation: string
  impact: string
  action_type: RevisionActionType
  action: string
  example: string
}

export interface Report {
  content_feedback: string
  delivery_feedback: string
  response_feedback: string
  slide_coverage: SlideCoverage[]
  filler_count: number
  word_count: number
  revisions?: Revision[]
  answer_structure_tip?: string
}

export type Stage = 'setup' | 'spar' | 'report' | 'history'

export interface ChatMessage {
  role: 'question' | 'answer' | 'verdict'
  personaId: PersonaId
  text: string
  questionType?: QuestionType
  rubric?: Record<string, string>
  answerStatus?: AnswerStatus
  supplement?: string | null
  relatedSlides?: number[]
}