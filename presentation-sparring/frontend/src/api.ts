import type {
  AcademicField,
  Difficulty,
  EvaluateResponse,
  PersonaId,
  QuestionResponse,
  Report,
  Slide,
  TranscriptTurn,
} from './types'

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8000'

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`API ${path} failed (${res.status}): ${detail}`)
  }
  return res.json() as Promise<T>
}

export function fetchQuestion(
  script: string,
  slides: Slide[],
  personaId: PersonaId,
  difficulty: Difficulty,
  field: AcademicField | null,
): Promise<QuestionResponse> {
  return post('/api/questions', {
    script,
    slides,
    persona_id: personaId,
    difficulty,
    field,
  })
}

export function evaluateAnswer(args: {
  script: string
  personaId: PersonaId
  question: string
  answer: string
  turn: number
  maxTurns: number
  field: AcademicField | null
  termHints?: string[]
}): Promise<EvaluateResponse> {
  return post('/api/evaluate', {
    script: args.script,
    persona_id: args.personaId,
    question: args.question,
    answer: args.answer,
    turn: args.turn,
    max_turns: args.maxTurns,
    field: args.field,
    term_hints: args.termHints ?? [],
  })
}

export function fetchReport(
  script: string,
  slides: Slide[],
  transcript: TranscriptTurn[],
  field: AcademicField | null,
): Promise<Report> {
  return post('/api/report', { script, slides, transcript, field })
}
