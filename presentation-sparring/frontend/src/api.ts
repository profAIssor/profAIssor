import type {
  AcademicField,
  Difficulty,
  EvaluateResponse,
  PersonaId,
  QuestionResponse,
  QuestionRole,
  QuestionType,
  Report,
  Slide,
  SlideExtractResponse,
  TranscriptTurn,
} from './types'

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8000'

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`API ${path} failed (${response.status}): ${detail}`)
  }

  return response.json() as Promise<T>
}

/** PPTX·PDF 파일의 페이지별 텍스트 추출 요청. */
export async function extractSlides(file: File): Promise<Slide[]> {
  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch(`${BASE}/api/slides/extract`, {
    method: 'POST',
    body: formData,
  })

  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`API /api/slides/extract failed (${response.status}): ${detail}`)
  }

  const data = (await response.json()) as SlideExtractResponse
  return data.slides
}

/** 발표 자료와 내부 슬라이드-대본 정렬 결과 기반 신규 질문 요청. */
export function fetchQuestion(
  script: string,
  slides: Slide[],
  personaId: PersonaId,
  difficulty: Difficulty,
  field: AcademicField | null,
  excludedQuestions: string[] = [],
): Promise<QuestionResponse> {
  return post('/api/questions', {
    script,
    slides,
    persona_id: personaId,
    difficulty,
    field,
    excluded_questions: excludedQuestions,
  })
}

/** 현재 질문 답변 평가 및 다음 질문 동작 결정 요청. */
export function evaluateAnswer(args: {
  script: string
  slides: Slide[]
  personaId: PersonaId
  rootQuestion: string
  rootQuestionType: QuestionType
  question: string
  questionType: QuestionType
  questionRole: QuestionRole
  questionFocus: string
  contextSlides: number[]
  expectedAnswerPoints: string[]
  answer: string
  turn: number
  maxTurns: number
  difficulty: Difficulty
  field: AcademicField | null
  termHints?: string[]
}): Promise<EvaluateResponse> {
  return post('/api/evaluate', {
    script: args.script,
    slides: args.slides,
    persona_id: args.personaId,
    root_question: args.rootQuestion,
    root_question_type: args.rootQuestionType,
    question: args.question,
    question_type: args.questionType,
    question_role: args.questionRole,
    question_focus: args.questionFocus,
    context_slides: args.contextSlides,
    expected_answer_points: args.expectedAnswerPoints,
    answer: args.answer,
    turn: args.turn,
    max_turns: args.maxTurns,
    difficulty: args.difficulty,
    field: args.field,
    term_hints: args.termHints ?? [],
    is_unknown_retry: args.questionRole === 'retry',
  })
}

/** 전체 질의응답 기록 기반 최종 리포트 요청. */
export function fetchReport(
  script: string,
  slides: Slide[],
  transcript: TranscriptTurn[],
  field: AcademicField | null,
): Promise<Report> {
  return post('/api/report', {
    script,
    slides,
    transcript,
    field,
  })
}