import { Mic, Send, Square } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { evaluateAnswer, fetchQuestion } from '../api'
import { useSpeechRecognition } from '../hooks/useSpeechRecognition'
import { buildTermDictionary, correctText } from '../lib/termCorrection'
import { getPersona } from '../personas'
import type {
  AcademicField,
  ChatMessage,
  Difficulty,
  EvaluationNextAction,
  PersonaId,
  QuestionResponse,
  QuestionRole,
  QuestionType,
  Slide,
  TranscriptTurn,
} from '../types'

interface Props {
  script: string
  slides: Slide[]
  personaIds: PersonaId[]
  difficulty: Difficulty
  maxTurns: number
  field: AcademicField | null
  onFinish: (transcript: TranscriptTurn[]) => void
}

interface QuestionState {
  question: string
  rootQuestion: string
  questionType: QuestionType
  rootQuestionType: QuestionType
  questionRole: QuestionRole
  questionFocus: string
  contextSlides: number[]
  expectedAnswerPoints: string[]
}

const QUESTION_STOPWORDS = new Set([
  '무엇인가요',
  '설명해',
  '주세요',
  '말씀해',
  '어떻게',
  '이유는',
  '근거는',
  '관련',
  '대해서',
  '자료',
  '발표',
])

/** 질문 문자열의 중복 비교용 정규화. */
function normalizeQuestion(question: string): string {
  return question.toLowerCase().replace(/[^a-z0-9가-힣]/g, '')
}

/** 질문 핵심 토큰 집합 생성. */
function questionTokens(question: string): Set<string> {
  const tokens = question.toLowerCase().match(/[a-z0-9가-힣]{2,}/g) ?? []
  return new Set(tokens.filter((token) => !QUESTION_STOPWORDS.has(token)))
}

/** 공백과 어미가 달라도 유사한 질문의 반복 판정. */
function isNearDuplicateQuestion(
  candidate: string,
  previousQuestions: string[],
): boolean {
  const candidateNormalized = normalizeQuestion(candidate)
  if (!candidateNormalized) return false
  const candidateTokens = questionTokens(candidate)

  return previousQuestions.some((previous) => {
    const previousNormalized = normalizeQuestion(previous)
    if (!previousNormalized) return false
    if (candidateNormalized === previousNormalized) return true

    const shorter =
      candidateNormalized.length <= previousNormalized.length
        ? candidateNormalized
        : previousNormalized
    const longer =
      candidateNormalized.length > previousNormalized.length
        ? candidateNormalized
        : previousNormalized
    if (shorter.length >= 12 && longer.includes(shorter)) return true

    const previousTokens = questionTokens(previous)
    const union = new Set([...candidateTokens, ...previousTokens])
    if (union.size === 0) return false
    const intersection = [...candidateTokens].filter((token) =>
      previousTokens.has(token),
    )
    return intersection.length / union.size >= 0.72
  })
}

/** 구버전 응답에 대한 다음 동작 보정. */
function resolveNextAction(
  action: EvaluationNextAction | undefined,
  hasRetry: boolean,
  hasFollowup: boolean,
  currentTurn: number,
  maxTurns: number,
): EvaluationNextAction {
  if (action) return action
  if (hasRetry) return 'retry_after_unknown'
  if (hasFollowup) return 'ask_followup'
  return currentTurn < maxTurns ? 'move_to_new_root' : 'finish'
}

/** 발표 자료 기반 질의응답 진행 및 질문 역할별 상태 관리. */
export default function SparScreen({
  script,
  slides,
  personaIds,
  difficulty,
  maxTurns,
  field,
  onFinish,
}: Props) {
  const [personaIndex, setPersonaIndex] = useState(0)
  // 현재 사용 중인 질문 슬롯의 0부터 시작하는 순번
  const [turn, setTurn] = useState(0)
  const [questionState, setQuestionState] = useState<QuestionState | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [answer, setAnswer] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [interim, setInterim] = useState('')
  const [readyForReport, setReadyForReport] = useState(false)
  const [unknownSupplement, setUnknownSupplement] = useState<string | null>(null)

  const transcriptRef = useRef<TranscriptTurn[]>([])
  // 신규 기본 질문의 전역 중복 방지 목록
  const askedRootQuestionsRef = useRef<string[]>([])
  // 현재 기본 질문 흐름 내부의 반복 방지 목록
  const currentQuestionChainRef = useRef<string[]>([])
  const startedRef = useRef(false)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const answerInputRef = useRef<HTMLTextAreaElement | null>(null)

  const termDict = useMemo(
    () => buildTermDictionary(script, slides),
    [script, slides],
  )

  const {
    supported: sttSupported,
    listening,
    micError,
    toggle: toggleMic,
    stop: stopMic,
  } = useSpeechRecognition({
    onFinal: (text) => {
      if (!text) return
      const corrected = correctText(text, termDict)
      setAnswer((previous) =>
        (previous.trim() ? `${previous.trimEnd()} ` : '') + corrected,
      )
    },
    onInterim: setInterim,
  })

  const activePersonaId = personaIds[personaIndex]
  const persona = getPersona(activePersonaId)
  const totalQuestionCount = maxTurns + 1
  const remainingQuestionCount = Math.max(0, totalQuestionCount - turn)
  const isUnknownRetryQuestion = questionState?.questionRole === 'retry'

  const pushMessage = (message: ChatMessage) => {
    setMessages((previous) => [...previous, message])
  }

  const registerRootQuestion = (question: string) => {
    if (!question.trim()) return
    if (!isNearDuplicateQuestion(question, askedRootQuestionsRef.current)) {
      askedRootQuestionsRef.current = [
        ...askedRootQuestionsRef.current,
        question,
      ]
    }
  }

  const applyQuestionResponse = (
    response: QuestionResponse,
    personaId: PersonaId,
    targetTurn: number,
  ) => {
    const nextState: QuestionState = {
      question: response.question,
      rootQuestion: response.question,
      questionType: response.question_type,
      rootQuestionType: response.question_type,
      questionRole: 'root',
      questionFocus: response.question_focus,
      contextSlides: response.context_slides,
      expectedAnswerPoints: response.expected_answer_points,
    }
    setTurn(targetTurn)
    setQuestionState(nextState)
    setUnknownSupplement(null)
    currentQuestionChainRef.current = [response.question]
    registerRootQuestion(response.question)
    pushMessage({
      role: 'question',
      personaId,
      text: response.question,
      questionType: response.question_type,
    })
  }

  /** 이전 무응답을 제외한 신규 기본 질문 로드. */
  const loadFreshQuestion = async (
    targetPersonaIndex: number,
    targetTurn: number,
  ) => {
    setBusy(true)
    setError(null)
    try {
      const personaId = personaIds[targetPersonaIndex]
      const response = await fetchQuestion(
        script,
        slides,
        personaId,
        difficulty,
        field,
        askedRootQuestionsRef.current,
      )
      applyQuestionResponse(response, personaId, targetTurn)
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : String(exception))
    } finally {
      setBusy(false)
    }
  }

  /** 다음 평가자 이동 또는 전체 완료 처리. */
  const moveToNextPersonaOrFinish = async () => {
    const nextPersonaIndex = personaIndex + 1
    if (nextPersonaIndex < personaIds.length) {
      setPersonaIndex(nextPersonaIndex)
      setQuestionState(null)
      setUnknownSupplement(null)
      currentQuestionChainRef.current = []
      await loadFreshQuestion(nextPersonaIndex, 0)
      return
    }

    setQuestionState(null)
    setReadyForReport(true)
  }

  /** 현재 질문 슬롯 종료 뒤 새 기본 질문 또는 다음 평가자 이동. */
  const advanceAfterCurrentQuestion = async (currentTurn: number) => {
    const nextTurn = currentTurn + 1
    setUnknownSupplement(null)
    if (nextTurn <= maxTurns) {
      await loadFreshQuestion(personaIndex, nextTurn)
      return
    }
    await moveToNextPersonaOrFinish()
  }

  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true
    void loadFreshQuestion(0, 0)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 최초 질문 1회 실행 보장
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [messages])

  useEffect(() => {
    if (!busy && questionState && !readyForReport) {
      answerInputRef.current?.focus()
    }
  }, [busy, questionState, readyForReport])

  const submit = async () => {
    if (!questionState || !answer.trim() || busy || readyForReport) return

    stopMic()
    setInterim('')

    const personaId = activePersonaId
    const currentState = questionState
    const currentTurn = turn
    const studentAnswer = answer.trim()

    setBusy(true)
    setError(null)
    pushMessage({ role: 'answer', personaId, text: studentAnswer })
    setAnswer('')

    try {
      const evaluation = await evaluateAnswer({
        script,
        slides,
        personaId,
        rootQuestion: currentState.rootQuestion,
        rootQuestionType: currentState.rootQuestionType,
        question: currentState.question,
        questionType: currentState.questionType,
        questionRole: currentState.questionRole,
        questionFocus: currentState.questionFocus,
        contextSlides: currentState.contextSlides,
        expectedAnswerPoints: currentState.expectedAnswerPoints,
        answer: studentAnswer,
        turn: currentTurn,
        maxTurns,
        difficulty,
        field,
        termHints: termDict,
      })

      const action = resolveNextAction(
        evaluation.next_action,
        Boolean(evaluation.retry_question),
        Boolean(evaluation.followup),
        currentTurn,
        maxTurns,
      )

      if (action === 'retry_after_unknown' && evaluation.retry_question) {
        pushMessage({
          role: 'verdict',
          personaId,
          text: '아래 기본 아이디어를 바탕으로 현재 질문의 답을 한 단계씩 유추해 보세요.',
          answerStatus: 'unknown',
          supplement: evaluation.supplement,
          relatedSlides: evaluation.related_slides,
        })

        const retryType =
          evaluation.retry_question_type ?? currentState.questionType
        const retryQuestion = evaluation.retry_question
        setUnknownSupplement(evaluation.supplement)
        setQuestionState({
          ...currentState,
          question: retryQuestion,
          questionType: retryType,
          questionRole: 'retry',
          questionFocus:
            evaluation.retry_question_focus || currentState.questionFocus,
          expectedAnswerPoints:
            evaluation.retry_expected_answer_points.length > 0
              ? evaluation.retry_expected_answer_points
              : currentState.expectedAnswerPoints,
        })
        currentQuestionChainRef.current = [
          ...currentQuestionChainRef.current,
          retryQuestion,
        ]
        pushMessage({
          role: 'question',
          personaId,
          text: retryQuestion,
          questionType: retryType,
        })
        return
      }

      const isUnknown = evaluation.answer_status === 'unknown'
      pushMessage({
        role: 'verdict',
        personaId,
        text: isUnknown
          ? '이 질문은 여기까지 하고 다음 기본 질문으로 넘어가겠습니다.'
          : `평가: ${evaluation.verdict} ✅ ${evaluation.strengths} ⚠️ ${evaluation.gaps}`,
        rubric: isUnknown ? undefined : evaluation.rubric,
        answerStatus: evaluation.answer_status,
      })

      // 무응답 재질문은 최초 무응답과 합쳐 질문 슬롯 한 개로 기록
      transcriptRef.current.push({
        persona_id: personaId,
        question: currentState.question,
        question_type: currentState.questionType,
        question_role: currentState.questionRole,
        answer: studentAnswer,
        verdict: evaluation.verdict,
        strengths: evaluation.strengths,
        gaps: evaluation.gaps,
        answer_status: evaluation.answer_status,
        supplement:
          currentState.questionRole === 'retry' ? unknownSupplement : null,
        related_slides:
          currentState.questionRole === 'retry'
            ? currentState.contextSlides
            : [],
        rubric: evaluation.rubric,
      })

      if (action === 'ask_followup' && evaluation.followup) {
        const nextTurn = currentTurn + 1
        const followup = evaluation.followup

        // 꼬리질문은 앞선 답변의 심화·확장이어야 하며 단순 반복은 신규 기본 질문으로 대체
        if (
          nextTurn > maxTurns ||
          isNearDuplicateQuestion(followup, currentQuestionChainRef.current)
        ) {
          await advanceAfterCurrentQuestion(currentTurn)
          return
        }

        const followupType =
          evaluation.followup_question_type ?? currentState.questionType
        setTurn(nextTurn)
        setUnknownSupplement(null)
        setQuestionState({
          ...currentState,
          question: followup,
          questionType: followupType,
          questionRole: 'followup',
          questionFocus:
            evaluation.followup_focus || currentState.questionFocus,
          expectedAnswerPoints:
            evaluation.followup_expected_answer_points.length > 0
              ? evaluation.followup_expected_answer_points
              : currentState.expectedAnswerPoints,
        })
        currentQuestionChainRef.current = [
          ...currentQuestionChainRef.current,
          followup,
        ]
        pushMessage({
          role: 'question',
          personaId,
          text: followup,
          questionType: followupType,
        })
        return
      }

      if (action === 'move_to_new_root') {
        await advanceAfterCurrentQuestion(currentTurn)
        return
      }

      await moveToNextPersonaOrFinish()
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : String(exception))
    } finally {
      setBusy(false)
    }
  }

  const openReport = () => {
    if (!readyForReport || busy) return
    onFinish([...transcriptRef.current])
  }

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key === 'Enter' &&
      !event.shiftKey &&
      !(event.nativeEvent as { isComposing?: boolean }).isComposing
    ) {
      event.preventDefault()
      void submit()
    }
  }

  return (
    <div className="mx-auto flex h-[calc(100dvh-8.5rem)] min-h-[480px] w-full max-w-4xl flex-col gap-4 sm:h-[calc(100dvh-10rem)] sm:min-h-[560px]">
      <div className="flex shrink-0 flex-col gap-3 rounded-2xl border border-slate-200/80 bg-white px-4 py-3.5 shadow-sm sm:flex-row sm:items-center sm:justify-between sm:px-5">
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 shrink-0 select-none items-center justify-center rounded-full bg-indigo-600 text-base font-bold text-white">
            {persona.emoji}
          </span>
          <div>
            <div className="text-base font-bold text-slate-800">{persona.name}</div>
            <div className="text-sm text-slate-500">
              남은 질문 횟수 {remainingQuestionCount}회
              <span className="ml-1.5 text-xs text-slate-400">
                {isUnknownRetryQuestion
                  ? '(현재 재질문은 차감 제외)'
                  : '(현재 질문 포함)'}
              </span>
            </div>
          </div>
        </div>

        <div className="flex min-w-0 items-center gap-2">
          <div className="flex min-w-0 flex-1 items-center gap-1.5 sm:flex-none sm:gap-2">
            {personaIds.map((personaId, index) => (
              <span
                key={personaId}
                className={
                  'h-2 min-w-4 flex-1 rounded-full sm:w-8 sm:flex-none ' +
                  (index <= personaIndex ? 'bg-indigo-400' : 'bg-slate-200')
                }
              />
            ))}
          </div>
          <span className="ml-1 shrink-0 text-sm font-semibold text-slate-500">
            {personaIndex + 1} / {personaIds.length}
          </span>
        </div>
      </div>

      <div
        ref={scrollRef}
        aria-live="polite"
        className="flex min-h-0 flex-1 flex-col space-y-4 overflow-y-auto rounded-2xl border border-slate-200/80 bg-white p-4 shadow-sm sm:p-5"
      >
        {messages.map((message, index) => {
          const messagePersona = getPersona(message.personaId)

          if (message.role === 'answer') {
            return (
              <div key={index} className="flex justify-end">
                <div className="max-w-[88%] whitespace-pre-wrap rounded-2xl rounded-tr-sm bg-indigo-600 px-4 py-3 text-base leading-relaxed text-white shadow-sm sm:max-w-[80%]">
                  {message.text}
                </div>
              </div>
            )
          }

          if (message.role === 'verdict') {
            const rubricEntries = message.rubric
              ? Object.entries(message.rubric)
              : []
            const relatedSlides = message.relatedSlides ?? []

            return (
              <div key={index} className="flex justify-center">
                <div className="w-full max-w-[96%] space-y-3 rounded-xl border border-slate-100 bg-slate-50 px-4 py-3.5 text-sm leading-relaxed text-slate-700 sm:max-w-[92%] sm:text-base">
                  <div className="whitespace-pre-wrap">{message.text}</div>

                  {message.answerStatus === 'unknown' && message.supplement && (
                    <div className="rounded-lg border border-indigo-100 bg-white px-3.5 py-3">
                      <div className="mb-1.5 text-sm font-bold text-indigo-700">
                        생각해 볼 기본 아이디어
                      </div>
                      <div className="whitespace-pre-wrap text-slate-700">
                        {message.supplement}
                      </div>
                    </div>
                  )}

                  {message.answerStatus === 'unknown' && relatedSlides.length > 0 && (
                    <div className="text-sm text-slate-600">
                      관련 발표 자료:{' '}
                      {relatedSlides
                        .map((slide) => `${slide}번 슬라이드`)
                        .join(', ')}
                    </div>
                  )}

                  {rubricEntries.length > 0 && (
                    <div className="flex flex-wrap gap-2 pt-0.5">
                      {rubricEntries.map(([axis, value]) => (
                        <span
                          key={axis}
                          className={
                            'rounded-full px-2.5 py-1 text-xs font-semibold ' +
                            (value === '우수'
                              ? 'bg-emerald-50 text-emerald-700'
                              : value === '보통'
                                ? 'bg-amber-50 text-amber-700'
                                : 'bg-rose-50 text-rose-700')
                          }
                        >
                          {axis} {value}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )
          }

          return (
            <div key={index} className="flex justify-start">
              <div className="max-w-[88%] rounded-2xl rounded-tl-sm border border-slate-200 bg-white px-4 py-3 text-base leading-relaxed shadow-sm sm:max-w-[80%]">
                <div className="mb-1.5 flex items-center gap-2 text-sm font-bold text-indigo-700">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-100 text-xs">
                    {messagePersona.emoji}
                  </span>
                  <span>{messagePersona.name}</span>
                </div>
                <span className="whitespace-pre-wrap text-slate-700">
                  {message.text}
                </span>
              </div>
            </div>
          )
        })}

        {busy && (
          <div className="flex justify-start">
            <div className="flex items-center gap-2 rounded-2xl rounded-tl-sm border border-slate-200 bg-white px-4 py-3 text-base text-slate-500 shadow-sm">
              생각 중…
              <div className="flex gap-1">
                {[0, 120, 240].map((delay) => (
                  <span
                    key={delay}
                    className="h-1.5 w-1.5 animate-bounce rounded-full bg-indigo-600"
                    style={{ animationDelay: `${delay}ms` }}
                  />
                ))}
              </div>
            </div>
          </div>
        )}

        {error && (
          <div className="rounded-xl border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-600">
            오류: {error}
          </div>
        )}

        {micError && !readyForReport && (
          <div className="rounded-xl border border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-700">
            {micError}
          </div>
        )}

        {listening && !readyForReport && (
          <div className="flex items-center gap-2 rounded-xl border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-rose-500" />
            <span className="font-semibold">받아쓰는 중…</span>
            <span className="min-w-0 text-slate-500">
              {interim || '(말해 보세요)'}
            </span>
          </div>
        )}
      </div>

      {readyForReport ? (
        <div className="flex shrink-0 flex-col gap-4 rounded-2xl border border-indigo-100 bg-indigo-50/70 px-5 py-4 shadow-sm sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-base font-bold text-slate-800">
              모든 질의응답이 완료되었습니다.
            </div>
            <div className="mt-1 text-sm leading-relaxed text-slate-600">
              마지막 답변의 피드백을 확인한 뒤 종합 리포트로 이동해 주세요.
            </div>
          </div>
          <button
            type="button"
            onClick={openReport}
            className="flex min-h-12 shrink-0 items-center justify-center gap-2 rounded-xl bg-indigo-600 px-5 py-3 text-base font-semibold text-white shadow-sm transition hover:bg-indigo-700"
          >
            종합 리포트 보기
          </button>
        </div>
      ) : (
        <div className="sticky bottom-0 z-10 flex shrink-0 gap-2 rounded-2xl border border-slate-200/80 bg-white/95 p-2.5 shadow-lg backdrop-blur sm:p-3">
          {sttSupported && (
            <button
              type="button"
              data-testid="mic-btn"
              onClick={toggleMic}
              disabled={busy || !questionState}
              title={listening ? '받아쓰기 중지' : '음성으로 답변 (STT)'}
              className={
                'flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border transition disabled:cursor-not-allowed disabled:opacity-40 ' +
                (listening
                  ? 'border-rose-300 bg-rose-50 text-rose-500'
                  : 'border-slate-200 bg-slate-50 text-slate-600 hover:border-indigo-400 hover:text-indigo-600')
              }
            >
              {listening ? (
                <Square className="h-4 w-4 fill-current" />
              ) : (
                <Mic className="h-5 w-5" />
              )}
            </button>
          )}

          <textarea
            ref={answerInputRef}
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
            onKeyDown={onKeyDown}
            disabled={busy || !questionState}
            rows={2}
            placeholder={
              sttSupported
                ? '답변을 입력하거나 마이크로 말하세요. (Enter 전송, Shift+Enter 줄바꿈)'
                : '답변을 입력하세요. (Enter 전송, Shift+Enter 줄바꿈)'
            }
            className="min-h-12 min-w-0 flex-1 resize-none rounded-xl border border-slate-200 bg-slate-50/50 px-3.5 py-3 text-base leading-relaxed text-slate-700 outline-none transition focus:border-indigo-500 focus:bg-white focus:ring-2 focus:ring-indigo-500 disabled:opacity-50 sm:px-4"
          />

          <button
            type="button"
            onClick={() => void submit()}
            disabled={busy || !questionState || !answer.trim()}
            aria-label="답변 전송"
            className="flex h-12 shrink-0 items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 text-base font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-40 sm:px-6"
          >
            <Send className="h-5 w-5" />
            <span className="hidden sm:inline">답변</span>
          </button>
        </div>
      )}
    </div>
  )
}