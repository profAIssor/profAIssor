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
  PersonaId,
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

  // 현재 평가자에서 표시된 추가 질문 횟수 관리
  const [turn, setTurn] = useState(0)

  // 현재 화면 질문의 답변 불가 뒤 쉬운 재질문 여부 관리
  const [isUnknownRetryQuestion, setIsUnknownRetryQuestion] = useState(false)

  const [question, setQuestion] = useState<string | null>(null)
  const [rootQuestion, setRootQuestion] = useState<string | null>(null)

  // 최초 질문 유형 및 현재 질문 유형 상태
  const [rootQuestionType, setRootQuestionType] =
    useState<QuestionType | null>(null)
  const [questionType, setQuestionType] = useState<QuestionType | null>(null)

  // 질문 자료 맥락 보존
  const [questionFocus, setQuestionFocus] = useState('')
  const [contextSlides, setContextSlides] = useState<number[]>([])
  const [expectedAnswerPoints, setExpectedAnswerPoints] = useState<string[]>([])

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [answer, setAnswer] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [interim, setInterim] = useState('')

  // 마지막 평가 확인 후 리포트 이동 상태
  const [readyForReport, setReadyForReport] = useState(false)

  const transcriptRef = useRef<TranscriptTurn[]>([])

  // 답변 불가 후 중복 질문 제외 목록
  const askedQuestionsRef = useRef<Partial<Record<PersonaId, string[]>>>({})

  const startedRef = useRef(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  // STT 용어 사전 재사용
  const termDict = useMemo(() => buildTermDictionary(script, slides), [script, slides])

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

  // 기본 질문을 포함한 현재 평가자의 전체 정상 질문 수 계산
  const totalQuestionCount = maxTurns + 1

  // 정상 질문에서는 현재 질문을 포함하고, 쉬운 재질문에서는 남은 정상 질문만 계산
  const remainingQuestionCount = isUnknownRetryQuestion
    ? Math.max(0, maxTurns - turn)
    : Math.max(0, totalQuestionCount - turn)

  const pushMessage = (message: ChatMessage) => {
    setMessages((previous) => [...previous, message])
  }

  // 페르소나별 최초 질문 및 자료 맥락 로드
  const loadFirstQuestion = async (targetPersonaIndex: number) => {
    setBusy(true)
    setError(null)

    try {
      const personaId = personaIds[targetPersonaIndex]
      const excludedQuestions = askedQuestionsRef.current[personaId] ?? []
      const response = await fetchQuestion(
        script,
        slides,
        personaId,
        difficulty,
        field,
        excludedQuestions,
      )

      askedQuestionsRef.current[personaId] = [
        ...excludedQuestions,
        response.question,
      ]

      setIsUnknownRetryQuestion(false)
      setQuestion(response.question)
      setRootQuestion(response.question)
      setRootQuestionType(response.question_type)
      setQuestionType(response.question_type)
      setQuestionFocus(response.question_focus)
      setContextSlides(response.context_slides)
      setExpectedAnswerPoints(response.expected_answer_points)

      pushMessage({
        role: 'question',
        personaId,
        text: response.question,
        questionType: response.question_type,
      })
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : String(exception))
    } finally {
      setBusy(false)
    }
  }

  // 개발 환경 이중 실행 방지
  useEffect(() => {
    if (startedRef.current) return

    startedRef.current = true
    void loadFirstQuestion(0)

    // eslint-disable-next-line react-hooks/exhaustive-deps -- 최초 질문 1회 실행 보장
  }, [])

  // 새 메시지 자동 스크롤
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [messages])

  const submit = async () => {
    if (!question || !answer.trim() || busy || readyForReport) return

    stopMic()
    setInterim('')

    const personaId = activePersonaId
    const currentQuestion = question
    const firstQuestion = rootQuestion ?? currentQuestion

    // 질문 유형 및 진행 상태의 이전 데이터 호환 처리
    const firstQuestionType = rootQuestionType ?? questionType ?? 'definition'
    const currentQuestionType = questionType ?? firstQuestionType
    const currentTurn = turn
    const currentIsUnknownRetry = isUnknownRetryQuestion
    const studentAnswer = answer.trim()

    setBusy(true)
    setError(null)

    pushMessage({
      role: 'answer',
      personaId,
      text: studentAnswer,
    })
    setAnswer('')

    try {
      const evaluation = await evaluateAnswer({
        script,
        slides,
        personaId,
        rootQuestion: firstQuestion,
        rootQuestionType: firstQuestionType,
        question: currentQuestion,
        questionType: currentQuestionType,
        questionFocus,
        contextSlides,
        expectedAnswerPoints,
        answer: studentAnswer,
        turn: currentTurn,
        maxTurns,
        difficulty,
        field,
        termHints: termDict,
        isUnknownRetry: currentIsUnknownRetry,
      })

      const isUnknown = evaluation.answer_status === 'unknown'
      const isFirstUnknown = isUnknown && !currentIsUnknownRetry
      const hasNextQuestion = Boolean(evaluation.followup)

      pushMessage({
        role: 'verdict',
        personaId,
        text: isUnknown
          ? isFirstUnknown && hasNextQuestion
            ? '힌트를 확인한 뒤 더 쉬운 질문으로 한 번만 다시 답해 보세요.'
            : hasNextQuestion
              ? '이 질문은 여기까지 하고 다음 질문으로 넘어가겠습니다.'
              : '이 질문은 여기까지 하고 다음 평가자로 넘어가겠습니다.'
          : `평가: ${evaluation.verdict}
✅ ${evaluation.strengths}
⚠️ ${evaluation.gaps}`,
        rubric: isUnknown ? undefined : evaluation.rubric,
        answerStatus: evaluation.answer_status,
        supplement: isFirstUnknown ? evaluation.supplement : undefined,
        relatedSlides: isFirstUnknown ? evaluation.related_slides : [],
      })

      transcriptRef.current.push({
        persona_id: personaId,
        question: currentQuestion,
        question_type: currentQuestionType,
        answer: studentAnswer,
        verdict: evaluation.verdict,
        strengths: evaluation.strengths,
        gaps: evaluation.gaps,
        // 1-4: 답변 불가 흐름 정보 + main(PR#15): 상세 교정 카드용 rubric
        answer_status: evaluation.answer_status,
        supplement: evaluation.supplement,
        related_slides: evaluation.related_slides,
        rubric: evaluation.rubric,
      })

      if (isFirstUnknown && evaluation.followup) {
        // 현재 정상 질문에 대한 쉬운 재질문 1회 전환
        const retryQuestionType =
          evaluation.followup_question_type ?? 'definition'

        setIsUnknownRetryQuestion(true)
        setQuestion(evaluation.followup)
        setQuestionType(retryQuestionType)
        setExpectedAnswerPoints([])

        pushMessage({
          role: 'question',
          personaId,
          text: evaluation.followup,
          questionType: retryQuestionType,
        })

        setBusy(false)
        return
      }

      if (evaluation.followup) {
        // 다음 정상 질문 전환 및 쉬운 재질문 상태 초기화
        const nextQuestionType =
          evaluation.followup_question_type ?? currentQuestionType

        setIsUnknownRetryQuestion(false)
        setQuestion(evaluation.followup)
        setQuestionType(nextQuestionType)
        setExpectedAnswerPoints([])
        setTurn(currentTurn + 1)

        pushMessage({
          role: 'question',
          personaId,
          text: evaluation.followup,
          questionType: nextQuestionType,
        })

        setBusy(false)
        return
      }

      // 다음 persona 이동 및 진행 상태 초기화
      const nextPersonaIndex = personaIndex + 1

      if (nextPersonaIndex < personaIds.length) {
        setPersonaIndex(nextPersonaIndex)
        setTurn(0)
        setIsUnknownRetryQuestion(false)
        setQuestion(null)
        setRootQuestion(null)
        setRootQuestionType(null)
        setQuestionType(null)
        setQuestionFocus('')
        setContextSlides([])
        setExpectedAnswerPoints([])

        await loadFirstQuestion(nextPersonaIndex)
        return
      }

      // 마지막 평가 확인 대기
      setQuestion(null)
      setReadyForReport(true)
      setBusy(false)
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : String(exception))
      setBusy(false)
    }
  }

  const openReport = () => {
    if (!readyForReport || busy) return
    onFinish([...transcriptRef.current])
  }

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault()
      void submit()
    }
  }

  return (
    <div className="mx-auto flex h-[calc(100dvh-8.5rem)] min-h-[480px] w-full max-w-4xl flex-col gap-4 sm:h-[calc(100dvh-10rem)] sm:min-h-[560px]">
      {/* 페르소나 배너 및 진행도 */}
      <div className="flex shrink-0 flex-col gap-3 rounded-2xl border border-slate-200/80 bg-white px-4 py-3.5 shadow-sm sm:flex-row sm:items-center sm:justify-between sm:px-5">
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 shrink-0 select-none items-center justify-center rounded-full bg-indigo-600 text-base font-bold text-white">
            {persona.emoji}
          </span>
          <div>
            <div className="text-base font-bold text-slate-800">{persona.name}</div>
            {/* 현재 화면 기준 남은 정상 질문 횟수 표시 */}
            <div className="text-sm text-slate-500">
              남은 질문 횟수 {remainingQuestionCount}회
              <span className="ml-1.5 text-xs text-slate-400">
                {isUnknownRetryQuestion
                  ? '(쉬운 재질문 제외)'
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
                  'h-2 min-w-5 flex-1 rounded-full sm:w-8 sm:flex-none ' +
                  (index < personaIndex
                    ? 'bg-indigo-600'
                    : index === personaIndex
                      ? 'animate-pulse bg-indigo-400'
                      : 'bg-slate-200')
                }
                title={getPersona(personaId).name}
              />
            ))}
          </div>
          <span className="ml-1 shrink-0 text-sm font-semibold text-slate-500">
            {personaIndex + 1} / {personaIds.length}
          </span>
        </div>
      </div>

      {/* 반응형 채팅 로그 */}
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
                        핵심 보충
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
                <span
                  className="h-1.5 w-1.5 animate-bounce rounded-full bg-indigo-600"
                  style={{ animationDelay: '0ms' }}
                />
                <span
                  className="h-1.5 w-1.5 animate-bounce rounded-full bg-indigo-600"
                  style={{ animationDelay: '150ms' }}
                />
                <span
                  className="h-1.5 w-1.5 animate-bounce rounded-full bg-indigo-600"
                  style={{ animationDelay: '300ms' }}
                />
              </div>
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="shrink-0 rounded-xl border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          오류: {error}
        </div>
      )}

      {micError && !readyForReport && (
        <div className="shrink-0 rounded-xl border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {micError}
        </div>
      )}

      {/* 실시간 받아쓰기 미리보기 */}
      {listening && !readyForReport && (
        <div className="flex shrink-0 flex-wrap items-center gap-2 text-sm text-indigo-700">
          <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-rose-500" />
          <span className="font-semibold">받아쓰는 중…</span>
          <span className="min-w-0 text-slate-500">
            {interim || '(말해 보세요)'}
          </span>
        </div>
      )}

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
        /* 답변 입력 영역 */
        <div className="sticky bottom-0 z-10 flex shrink-0 gap-2 rounded-2xl border border-slate-200/80 bg-white/95 p-2.5 shadow-lg backdrop-blur sm:p-3">
          {sttSupported && (
            <button
              type="button"
              data-testid="mic-btn"
              onClick={toggleMic}
              disabled={busy || !question}
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
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
            onKeyDown={onKeyDown}
            disabled={busy || !question}
            rows={2}
            placeholder={
              sttSupported
                ? '답변을 입력하거나 마이크로 말하세요. (Ctrl/⌘ + Enter 전송)'
                : '답변을 입력하세요. (Ctrl/⌘ + Enter 전송)'
            }
            className="min-h-12 min-w-0 flex-1 resize-none rounded-xl border border-slate-200 bg-slate-50/50 px-3.5 py-3 text-base leading-relaxed text-slate-700 outline-none transition focus:border-indigo-500 focus:bg-white focus:ring-2 focus:ring-indigo-500 disabled:opacity-50 sm:px-4"
          />

          <button
            type="button"
            onClick={() => void submit()}
            disabled={busy || !question || !answer.trim()}
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