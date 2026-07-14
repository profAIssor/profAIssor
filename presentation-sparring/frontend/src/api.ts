import type {
  AcademicField,
  Difficulty,
  EvaluateResponse,
  PersonaId,
  QuestionResponse,
  Report,
  Slide,
  SlideExtractResponse,
  TranscriptTurn,
} from './types'

const BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8000'

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

export async function extractSlides(file: File): Promise<Slide[]> {
  const formData = new FormData()
  formData.append('file', file)

  const res = await fetch(`${BASE}/api/slides/extract`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`API /api/slides/extract failed (${res.status}): ${detail}`)
  }

  const data = (await res.json()) as SlideExtractResponse
  return data.slides
}

export function fetchQuestion(
  script: string,
  slides: Slide[],
  personaId: PersonaId,
  difficulty: Difficulty,
  field: AcademicField | null,
): Promise<QuestionResponse> {
  return post<QuestionResponse>('/api/questions', {
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
  rootQuestion: string
  question: string
  answer: string
  turn: number
  maxTurns: number
  difficulty: Difficulty
  field: AcademicField | null
  termHints?: string[]
}): Promise<EvaluateResponse> {
  return post<EvaluateResponse>('/api/evaluate', {
    script: args.script,
    persona_id: args.personaId,
    root_question: args.rootQuestion,
    question: args.question,
    answer: args.answer,
    turn: args.turn,
    max_turns: args.maxTurns,
    difficulty: args.difficulty,
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
  return post<Report>('/api/report', {
    script,
    slides,
    transcript,
    field,
  })
}