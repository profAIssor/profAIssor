export type PersonaId = 'professor' | 'peer' | 'layperson'

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
  targets_slide: number | null
}

export interface EvaluateResponse {
  verdict: string
  strengths: string
  gaps: string
  followup: string | null
}

export interface TranscriptTurn {
  persona_id: string
  question: string
  answer: string
  verdict: string
  gaps: string
}

export interface SlideCoverage {
  index: number
  covered: boolean
  missing_point: string | null
}

export interface Report {
  content_feedback: string
  delivery_feedback: string
  response_feedback: string
  slide_coverage: SlideCoverage[]
  filler_count: number
  word_count: number
}

export type Stage = 'setup' | 'spar' | 'report'

/** A message rendered in the chat-style spar screen. */
export interface ChatMessage {
  role: 'question' | 'answer' | 'verdict'
  personaId: PersonaId
  text: string
}
