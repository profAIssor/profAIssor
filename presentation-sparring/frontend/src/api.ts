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

const BASE =
  (import.meta.env.VITE_API_BASE as
    | string
    | undefined) ?? 'http://localhost:8000'

const REQUEST_TIMEOUT_MS = 15_000
const RETRY_DELAY_MS = 600
const RETRYABLE_STATUS_CODES = new Set([
  429,
  500,
  502,
  503,
  504,
])

interface ErrorPayload {
  detail?: unknown
  message?: unknown
}

class ApiRequestError extends Error {
  constructor(
    message: string,
    readonly retryable: boolean,
  ) {
    super(message)
    this.name = 'ApiRequestError'
  }
}

/** 재시도 간 대기. */
function wait(delayMs: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, delayMs)
  })
}

/** 백엔드 오류 본문의 사용자 메시지 추출. */
async function readErrorDetail(
  response: Response,
): Promise<string> {
  const rawText = await response
    .text()
    .catch(() => '')

  if (!rawText.trim()) return ''

  try {
    const payload = JSON.parse(rawText) as ErrorPayload
    if (
      typeof payload.detail === 'string' &&
      payload.detail.trim()
    ) {
      return payload.detail.trim()
    }
    if (
      typeof payload.message === 'string' &&
      payload.message.trim()
    ) {
      return payload.message.trim()
    }
  } catch {
    // JSON이 아닌 오류 본문 처리
  }

  return rawText.trim()
}

/** 상태코드별 사용자 노출 메시지 생성. */
function resolveErrorMessage(
  status: number,
  detail: string,
): string {
  if (status === 400 || status === 422) {
    return (
      detail ||
      '입력 내용을 확인한 뒤 다시 시도해 주세요.'
    )
  }
  if (status === 413) {
    return (
      detail ||
      '업로드한 파일이나 입력 내용이 허용 범위를 초과했습니다.'
    )
  }
  if (status === 429) {
    return '요청이 일시적으로 많습니다. 잠시 후 다시 시도해 주세요.'
  }
  if (
    status === 500 ||
    status === 502 ||
    status === 503 ||
    status === 504
  ) {
    return (
      detail ||
      'AI 서비스 응답이 일시적으로 불안정합니다. 잠시 후 다시 시도해 주세요.'
    )
  }
  if (status === 404) {
    return '요청한 기능을 서버에서 찾을 수 없습니다.'
  }

  return (
    detail ||
    '요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.'
  )
}

/** 타임아웃·재시도·오류 정규화를 포함한 공통 요청. */
async function request<T>(
  path: string,
  init: RequestInit,
): Promise<T> {
  let lastError: Error | null = null

  for (let attempt = 0; attempt < 2; attempt += 1) {
    const controller = new AbortController()
    const timeoutId = window.setTimeout(() => {
      controller.abort()
    }, REQUEST_TIMEOUT_MS)

    try {
      const response = await fetch(
        `${BASE}${path}`,
        {
          ...init,
          signal: controller.signal,
        },
      )

      if (!response.ok) {
        const detail = await readErrorDetail(response)
        const retryable =
          RETRYABLE_STATUS_CODES.has(response.status)

        if (retryable && attempt === 0) {
          await wait(RETRY_DELAY_MS)
          continue
        }

        throw new ApiRequestError(
          resolveErrorMessage(
            response.status,
            detail,
          ),
          retryable,
        )
      }

      return (await response.json()) as T
    } catch (caught) {
      const exception =
        caught instanceof Error
          ? caught
          : new Error(String(caught))

      if (exception.name === 'AbortError') {
        // 백엔드의 LLM 호출은 클라이언트 취소 후에도 진행될 수 있으므로
        // 타임아웃 자동 재시도로 중복 과금되는 상황 방지
        lastError = new Error(
          '서버 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.',
        )
        break
      }

      if (exception instanceof TypeError) {
        lastError = new Error(
          '서버에 연결할 수 없습니다. 네트워크 상태와 서버 실행 여부를 확인해 주세요.',
        )
        if (attempt === 0) {
          await wait(RETRY_DELAY_MS)
          continue
        }
        break
      }

      if (exception instanceof ApiRequestError) {
        lastError = exception
        if (
          exception.retryable &&
          attempt === 0
        ) {
          await wait(RETRY_DELAY_MS)
          continue
        }
        break
      }

      lastError = exception
      break
    } finally {
      window.clearTimeout(timeoutId)
    }
  }

  throw (
    lastError ??
    new Error(
      '요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.',
    )
  )
}

/** JSON POST 요청. */
async function post<T>(
  path: string,
  body: unknown,
): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
    },
    body: JSON.stringify(body),
  })
}

/** PPTX·PDF 파일의 페이지별 텍스트 추출 요청. */
export async function extractSlides(
  file: File,
): Promise<Slide[]> {
  const formData = new FormData()
  formData.append('file', file)

  const data = await request<SlideExtractResponse>(
    '/api/slides/extract',
    {
      method: 'POST',
      body: formData,
    },
  )
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
    expected_answer_points:
      args.expectedAnswerPoints,
    answer: args.answer,
    turn: args.turn,
    max_turns: args.maxTurns,
    difficulty: args.difficulty,
    field: args.field,
    term_hints: args.termHints ?? [],
    is_unknown_retry:
      args.questionRole === 'retry',
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