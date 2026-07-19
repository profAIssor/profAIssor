export type PersonaId = 'standard' | 'professor' | 'peer' | 'layperson'

export type Difficulty = 'easy' | 'medium' | 'hard'
export type AcademicField = 'engineering' | 'humanities' | 'natural'

export type QuestionType =
  | 'evidence'
  | 'counterexample'
  | 'application'
  | 'definition'

export type AnswerStatus = 'answered' | 'unknown'

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
  followup: string | null
  followup_question_type: QuestionType | null
  answer_status: AnswerStatus
  supplement: string | null
  related_slides: number[]
  rubric: Record<string, string>
}

export interface TranscriptTurn {
  persona_id: string
  question: string
  question_type?: QuestionType
  answer: string
  verdict: string
  strengths: string
  gaps: string
  // 1-4: 답변 불가 흐름용 필드 (unknown 턴의 보충 힌트 표시)
  answer_status?: AnswerStatus
  supplement?: string | null
  related_slides?: number[]
  // main(PR#15): 답변별 상세 교정 카드에서 rubric 표시
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

  // 1-4C: 관찰→영향→수정 행동→수정 예시 구조의 구체적 코칭
  // 옵셔널로 두어 이전에 저장된 localStorage 세션(SessionRecord)도
  // 필드 없이 그대로 렌더링될 수 있게 함
  revisions?: Revision[]
  answer_structure_tip?: string
}

export type Stage = 'setup' | 'spar' | 'report' | 'history'

/** A message rendered in the chat-style spar screen. */
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