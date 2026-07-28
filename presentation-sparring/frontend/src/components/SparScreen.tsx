import { Lightbulb, Mic, Send, Square } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  evaluateAnswer,
  fetchFollowup,
  fetchQuestion,
} from '../api'
import { useMicMetrics } from '../hooks/useMicMetrics'
import { useSpeechRecognition } from '../hooks/useSpeechRecognition'
import { getBrowserSupport } from '../lib/browserSupport'
import {
  buildSpeechContextPhrases,
  buildTermDictionary,
  correctText,
  mergeSpeechTermAliases,
} from '../lib/termCorrection'
import { getPersona } from '../personas'
import type {
  AcademicField,
  ChatMessage,
  Difficulty,
  EvaluationNextAction,
  FollowupResponse,
  PersonaId,
  QuestionResponse,
  QuestionRole,
  QuestionType,
  Slide,
  SparringLanguage,
  SpeechMetrics,
  SpeechTermAlias,
  TranscriptTurn,
} from '../types'

interface Props {
  script: string
  slides: Slide[]
  personaIds: PersonaId[]
  difficulty: Difficulty
  language: SparringLanguage
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
  speechTermAliases: SpeechTermAlias[]
}


interface PendingUnknownAttempt {
  question: string
  questionType: QuestionType
  questionFocus: string
  expectedAnswerPoints: string[]
  answer: string
  supplement: string | null
  relatedSlides: number[]
  speechMetrics?: SpeechMetrics
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
  'what',
  'how',
  'why',
  'could',
  'would',
  'please',
  'explain',
  'describe',
  'presentation',
  'the',
  'and',
  'from',
])

// 백엔드는 난이도별로 기본 질문을 재생성하고, 이 값은 이미 받은 질문과
// 꼬리질문을 화면에 중복 삽입하지 않기 위한 마지막 로컬 안전망입니다.
const LOCAL_QUESTION_DUPLICATE_THRESHOLD = 0.72

const DIFFICULTY_LABELS: Record<Difficulty, string> = {
  easy: '쉬움',
  medium: '보통',
  hard: '어려움',
}

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
    return (
      intersection.length / union.size >=
      LOCAL_QUESTION_DUPLICATE_THRESHOLD
    )
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


interface RecoveryTip {
  guide: string
  example: Record<SparringLanguage, string>
}

const GENERAL_RECOVERY_TIPS: readonly RecoveryTip[] = [
  {
    guide: '질문을 한 문장으로 짧게 되짚으면 질문을 정확히 확인하면서 답변을 정리할 시간을 확보할 수 있습니다. 이렇게 말해 보세요: {example}',
    example: {
      ko: '“질문하신 핵심은 …로 이해했습니다.”',
      en: '“If I understand correctly, the key point is …”',
    },
  },
  {
    guide: '급하게 말을 채우지 말고 한두 박자 쉬어도 괜찮습니다. 숨을 천천히 내쉰 뒤 이렇게 시작해 보세요: {example}',
    example: {
      ko: '“먼저 결론부터 말씀드리면…”',
      en: '“The main point is …”',
    },
  },
  {
    guide: '바로 답이 떠오르지 않으면 답변 범위를 먼저 정한 뒤 첫 번째 내용부터 이어가 보세요: {example}',
    example: {
      ko: '“두 가지로 나누어 말씀드리겠습니다.”',
      en: '“I would break this into two points.”',
    },
  },
  {
    guide: '질문이 넓거나 의미가 애매하면 다시 확인해도 됩니다. 이는 회피가 아니라 정확한 답변을 위한 과정입니다: {example}',
    example: {
      ko: '“말씀하신 부분을 … 관점으로 이해하면 될까요?”',
      en: '“Should I address this from the perspective of …?”',
    },
  },
  {
    guide: '정확한 세부사항이 떠오르지 않으면 아는 범위와 확인이 필요한 범위를 나누어 답해 보세요: {example}',
    example: {
      ko: '“정확한 수치는 추가 확인이 필요하지만, 현재 말씀드릴 수 있는 범위는 …입니다.”',
      en: '“I would need to verify the exact figure, but the key mechanism is …”',
    },
  },
  {
    guide: '답변을 짧게 정리하려면 결론→이유→예시→결론 순서를 사용해 보세요. 우선 결론 한 문장만 말하면 다음 내용을 이어가기 쉽습니다: {example}',
    example: {
      ko: '“결론부터 말씀드리면 …입니다.”',
      en: '“To start with the conclusion, …”',
    },
  },
]

const SLIDE_RECOVERY_TIPS: readonly RecoveryTip[] = [
  {
    guide: '관련 슬라이드로 시선을 옮겨 해당 부분을 가리키며 답변을 이어가 보세요: {example}',
    example: {
      ko: '“자료를 기준으로 순서대로 설명드리겠습니다.”',
      en: '“Let me walk through this using the slide.”',
    },
  },
  {
    guide: '관련 슬라이드를 찾는 동안 먼저 안내 문장을 말해 보세요. 슬라이드를 확인하는 짧은 시간도 자연스러운 발표 진행의 일부입니다: {example}',
    example: {
      ko: '“질문과 연결되는 자료를 보면서 설명드리겠습니다.”',
      en: '“I will refer to the material connected to your question.”',
    },
  },
  {
    guide: '표나 그림이 있다면 제목이나 축을 먼저 가리키며 시작해 보세요. 시각 자료를 기준점으로 삼으면 말의 흐름을 다시 잡기 쉽습니다: {example}',
    example: {
      ko: '“이 자료에서 먼저 보셔야 할 부분은 …입니다.”',
      en: '“The first thing to notice here is …”',
    },
  },
]

function renderRecoveryTip(tip: RecoveryTip, language: SparringLanguage): string {
  return tip.guide.replace('{example}', tip.example[language])
}

/** 내용 힌트 없이 발표 진행 시간을 확보하는 침묵 회복 팁 생성. */
function buildLongSilenceTip(
  questionState: QuestionState,
  tipSequence: number,
  language: SparringLanguage,
): string {
  const tips: readonly RecoveryTip[] = questionState.contextSlides.length > 0
    ? [...GENERAL_RECOVERY_TIPS, ...SLIDE_RECOVERY_TIPS]
    : GENERAL_RECOVERY_TIPS

  const questionSeed = Array.from(
    questionState.question,
  ).reduce(
    (sum, character) =>
      sum + (character.codePointAt(0) ?? 0),
    0,
  )
  const selectedIndex =
    Math.abs(questionSeed + tipSequence) % tips.length

  return renderRecoveryTip(tips[selectedIndex], language)
}

/** 발표 자료 기반 질의응답 진행 및 질문 역할별 상태 관리. */
export default function SparScreen({
  script,
  slides,
  personaIds,
  difficulty,
  language,
  maxTurns,
  field,
  onFinish,
}: Props) {
  const isEnglish = language === 'en'
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

  const transcriptRef = useRef<TranscriptTurn[]>([])
  const pendingUnknownAttemptRef =
    useRef<PendingUnknownAttempt | null>(null)
  // 신규 기본 질문의 전역 중복 방지 목록
  const askedRootQuestionsRef = useRef<string[]>([])
  // 현재 기본 질문 흐름 내부의 반복 방지 목록
  const currentQuestionChainRef = useRef<string[]>([])
  // 다음 기본 질문의 프리페치 캐시.
  // 질문 생성이 평가 응답 뒤에 직렬로 붙지 않도록, 현재 질문을 띄우는 즉시
  // 다음 질문 생성을 시작해 사용자가 답변하는 시간과 겹쳐 놓는다.
  const prefetchedQuestionRef = useRef<{
    personaIndex: number
    promise: Promise<QuestionResponse | null>
  } | null>(null)
  const startedRef = useRef(false)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const answerInputRef = useRef<HTMLTextAreaElement | null>(null)
  const answerRef = useRef('')
  const handledLongSilenceSignalRef = useRef(0)

  const browserSupport = useMemo(() => getBrowserSupport(), [])
  const termDict = useMemo(
    () => buildTermDictionary(script, slides),
    [script, slides],
  )
  const speechContextPhrases = useMemo(() => {
    if (!questionState) return []

    const contextSlideIndices = new Set(
      questionState.contextSlides,
    )
    return buildSpeechContextPhrases({
      question: questionState.question,
      slides: slides.filter((slide) =>
        contextSlideIndices.has(slide.index),
      ),
    })
  }, [questionState, slides])
  const speechTermAliases = useMemo(
    () => questionState?.speechTermAliases ?? [],
    [questionState],
  )
  const speechRecognitionPhrases = useMemo(
    () => [
      ...new Set([
        ...speechContextPhrases,
        ...speechTermAliases.flatMap(({ canonical, aliases }) => [
          canonical,
          ...aliases,
        ]),
      ]),
    ],
    [speechContextPhrases, speechTermAliases],
  )
  const evaluationTermHints = useMemo(
    () => [
      ...new Set([
        ...speechContextPhrases,
        ...termDict,
      ]),
    ],
    [speechContextPhrases, termDict],
  )

  const {
    available: metricAvailable,
    recording: metricRecording,
    error: metricError,
    longSilenceSignal,
    startUserSegment,
    stopUserSegment,
    finalizeAnswer,
    resetAnswer: resetSpeechMetrics,
  } = useMicMetrics()

  const {
    supported: sttSupported,
    listening,
    micError,
    start: startMic,
    stopAndFlush,
    getTranscript,
    getRecognizedFillerMinimum,
    resetTranscript,
  } = useSpeechRecognition({
    lang: language === 'en' ? 'en-US' : 'ko-KR',
    contextPhrases: speechRecognitionPhrases,
    onFinal: (text) => {
      if (!text) return
      const previous = answerRef.current
      const combined =
        (previous.trim()
          ? `${previous.trimEnd()} `
          : '') + text
      const nextAnswer = correctText(
        combined,
        speechContextPhrases,
        speechTermAliases,
      )
      answerRef.current = nextAnswer
      setAnswer(nextAnswer)
    },
    onInterim: (text) =>
      setInterim(
        correctText(
          text,
          speechContextPhrases,
          speechTermAliases,
        ),
      ),
  })

  const activePersonaId = personaIds[personaIndex]
  const persona = getPersona(activePersonaId)
  const totalQuestionCount = maxTurns + 1
  const remainingQuestionCount = readyForReport
    ? 0
    : Math.max(0, totalQuestionCount - turn)
  const isUnknownRetryQuestion = questionState?.questionRole === 'retry'
  const displayedMicError = micError ?? metricError
  const voiceInputAvailable =
    browserSupport.supported && sttSupported

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

  /**
   * 다음 기본 질문이 어느 평가자에게서 나올지 계산.
   *
   * turn은 꼬리질문까지 포함한 슬롯 카운터이므로, 같은 평가자에게 남은
   * 슬롯이 있으면 동일 평가자가, 없으면 다음 평가자가 대상이 된다.
   * 모든 평가자를 소진했으면 프리페치 대상이 없다는 뜻으로 null을 반환한다.
   */
  const resolveNextQuestionPersonaIndex = (
    currentPersonaIndex: number,
    currentTurn: number,
  ): number | null => {
    if (currentTurn + 1 <= maxTurns) {
      return currentPersonaIndex
    }
    const nextPersonaIndex = currentPersonaIndex + 1
    return nextPersonaIndex < personaIds.length ? nextPersonaIndex : null
  }

  /**
   * 다음 기본 질문을 백그라운드로 미리 생성.
   *
   * /api/questions 요청은 현재 답변이나 평가 결과에 의존하지 않고
   * 중복 제외 목록만 사용하므로, 답변 제출 전에 실행해도 결과가 달라지지 않는다.
   * 실패는 화면에 노출하지 않고 null로 흡수해, 실제 소비 시점의 일반 호출로 되돌린다.
   */
  const prefetchNextQuestion = (targetPersonaIndex: number) => {
    const promise = fetchQuestion(
      script,
      slides,
      personaIds[targetPersonaIndex],
      difficulty,
      field,
      language,
      // 프리페치 시점의 목록을 고정해, 이후 참조 변경의 영향을 받지 않게 한다
      [...askedRootQuestionsRef.current],
    ).catch(() => null)

    prefetchedQuestionRef.current = {
      personaIndex: targetPersonaIndex,
      promise,
    }
  }

  const applyQuestionResponse = (
    response: QuestionResponse,
    targetPersonaIndex: number,
    targetTurn: number,
  ) => {
    const personaId = personaIds[targetPersonaIndex]
    const nextState: QuestionState = {
      question: response.question,
      rootQuestion: response.question,
      questionType: response.question_type,
      rootQuestionType: response.question_type,
      questionRole: 'root',
      questionFocus: response.question_focus,
      contextSlides: response.context_slides,
      expectedAnswerPoints: response.expected_answer_points,
      speechTermAliases: response.speech_term_aliases ?? [],
    }
    setTurn(targetTurn)
    setQuestionState(nextState)
    pendingUnknownAttemptRef.current = null
    currentQuestionChainRef.current = [response.question]
    registerRootQuestion(response.question)
    pushMessage({
      role: 'question',
      personaId,
      text: response.question,
      questionType: response.question_type,
    })

    // 방금 띄운 질문까지 중복 제외 목록에 등록된 뒤에 프리페치를 시작해야
    // 다음 질문이 현재 질문과 겹치지 않는다.
    prefetchedQuestionRef.current = null
    const nextPersonaIndex = resolveNextQuestionPersonaIndex(
      targetPersonaIndex,
      targetTurn,
    )
    if (nextPersonaIndex !== null) {
      prefetchNextQuestion(nextPersonaIndex)
    }
  }

  /** 이전 무응답을 제외한 신규 기본 질문 로드. */
  const loadFreshQuestion = async (
    targetPersonaIndex: number,
    targetTurn: number,
  ) => {
    setBusy(true)
    setError(null)
    try {
      // 같은 평가자를 대상으로 한 프리페치가 있으면 재사용한다.
      // 프리페치 이후에는 꼬리질문만 진행되고 기본 질문은 추가되지 않으므로
      // 중복 제외 목록이 그대로 유효하다.
      const cached = prefetchedQuestionRef.current
      prefetchedQuestionRef.current = null

      let response: QuestionResponse | null =
        cached && cached.personaIndex === targetPersonaIndex
          ? await cached.promise
          : null

      // 프리페치가 없거나 실패했으면 평소대로 직접 요청한다
      if (!response) {
        response = await fetchQuestion(
          script,
          slides,
          personaIds[targetPersonaIndex],
          difficulty,
          field,
          language,
          askedRootQuestionsRef.current,
        )
      }

      applyQuestionResponse(response, targetPersonaIndex, targetTurn)
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
      pendingUnknownAttemptRef.current = null
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
    pendingUnknownAttemptRef.current = null
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

  useEffect(() => {
    if (micError && metricRecording) {
      stopUserSegment()
    }
  }, [metricRecording, micError, stopUserSegment])


  useEffect(() => {
    if (
      longSilenceSignal <= handledLongSilenceSignalRef.current
    ) {
      return
    }

    if (
      !metricRecording ||
      busy ||
      !questionState
    ) {
      return
    }

    handledLongSilenceSignalRef.current = longSilenceSignal
    setMessages((previous) => [
      ...previous,
      {
        role: 'tip',
        personaId: activePersonaId,
        text: buildLongSilenceTip(
          questionState,
          longSilenceSignal,
          language,
        ),
      },
    ])
  }, [
    activePersonaId,
    busy,
    longSilenceSignal,
    metricRecording,
    questionState,
    language,
  ])

  /** textarea와 ref의 답변 동기화. */
  const updateAnswer = (value: string) => {
    answerRef.current = value
    setAnswer(value)
  }

  /** STT와 RMS 수집의 사용자 마이크 버튼 동기화. */
  const handleMicToggle = async () => {
    if (
      busy ||
      !questionState ||
      !voiceInputAvailable
    ) {
      return
    }

    if (listening) {
      stopUserSegment()
      await stopAndFlush()
      setInterim('')
      return
    }

    const started = startMic()
    const metricStarted = metricAvailable
      ? await startUserSegment()
      : false
    if (!started && metricStarted) {
      stopUserSegment()
    }
  }

  const submit = async () => {
    if (!questionState || busy || readyForReport) return

    let rawFinalSttText = getTranscript()

    if (listening) {
      stopUserSegment()
      rawFinalSttText = await stopAndFlush()
    }

    setInterim('')

    const studentAnswer = answerRef.current.trim()
    if (!studentAnswer) return

    const recognizedFillerMinimum =
      getRecognizedFillerMinimum()
    const speechMetrics = finalizeAnswer(
      rawFinalSttText,
      studentAnswer,
      recognizedFillerMinimum,
    )
    resetTranscript()

    const personaId = activePersonaId
    const currentState = questionState
    const currentTurn = turn

    setBusy(true)
    setError(null)
    pushMessage({ role: 'answer', personaId, text: studentAnswer })
    updateAnswer('')

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
        language,
        termHints: evaluationTermHints,
      })

      const action = resolveNextAction(
        evaluation.next_action,
        Boolean(evaluation.retry_question),
        Boolean(evaluation.followup),
        currentTurn,
        maxTurns,
      )

      if (action === 'retry_after_unknown' && evaluation.retry_question) {
        pendingUnknownAttemptRef.current = {
          question: currentState.question,
          questionType: currentState.questionType,
          // 재질문이 currentState를 덮어쓰기 전에 원질문의 자료 근거를 보존한다
          questionFocus: currentState.questionFocus,
          expectedAnswerPoints: currentState.expectedAnswerPoints,
          answer: studentAnswer,
          supplement: evaluation.supplement,
          relatedSlides: evaluation.related_slides,
          ...(speechMetrics
            ? { speechMetrics }
            : {}),
        }
        resetSpeechMetrics()

        pushMessage({
          role: 'verdict',
          personaId,
          text: '아래 단서를 바탕으로 현재 질문의 답을 한 단계씩 유추해 보세요.',
          answerStatus: 'unknown',
          supplement: evaluation.supplement,
          supplementTitle: '생각해 볼 단서',
          relatedSlides: evaluation.related_slides,
        })

        const retryType =
          evaluation.retry_question_type ?? currentState.questionType
        const retryQuestion = evaluation.retry_question
        setQuestionState({
          ...currentState,
          question: retryQuestion,
          questionType: retryType,
          questionRole: 'retry',
          questionFocus:
            evaluation.retry_question_focus || retryQuestion,
          // 재질문 계약이 비어도 원질문의 평가 기준으로 되돌아가지 않는다.
          // 쉬운 재질문은 현재 문장과 자료 범위만으로 평가한다.
          expectedAnswerPoints:
            evaluation.retry_expected_answer_points,
          speechTermAliases: mergeSpeechTermAliases(
            currentState.speechTermAliases,
            evaluation.retry_speech_term_aliases ?? [],
          ),
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
      const pendingUnknown =
        currentState.questionRole === 'retry'
          ? pendingUnknownAttemptRef.current
          : null

      if (isUnknown && currentState.questionRole === 'retry') {
        pushMessage({
          role: 'verdict',
          personaId,
          text: '재질문에도 답변하지 못했습니다. 아래 개념 설명을 확인한 뒤 이 질문과 관련된 내용을 다시 학습해 주세요.',
          answerStatus: 'unknown',
          supplement: evaluation.supplement,
          supplementTitle: '개념 정리',
          learningNote:
            evaluation.gaps ||
            '이 질문과 관련된 개념을 발표 전에 다시 학습해 주세요.',
          relatedSlides: evaluation.related_slides,
        })
      } else {
        pushMessage({
          role: 'verdict',
          personaId,
          text: isUnknown
            ? '현재 답변에서는 질문의 핵심을 확인하기 어려웠습니다.'
            : `평가: ${evaluation.verdict} ✅ ${evaluation.strengths} ⚠️ ${evaluation.gaps}`,
          rubric: isUnknown ? undefined : evaluation.rubric,
          answerStatus: evaluation.answer_status,
          supplement: evaluation.supplement,
          supplementTitle: evaluation.supplement
            ? '개념 정리'
            : undefined,
          relatedSlides: evaluation.related_slides,
        })
      }

      if (pendingUnknown) {
        transcriptRef.current.push({
          persona_id: personaId,
          question: pendingUnknown.question,
          question_type: pendingUnknown.questionType,
          question_role: 'retry',
          answer: pendingUnknown.answer,
          verdict: evaluation.verdict,
          strengths: evaluation.strengths,
          gaps: evaluation.gaps,
          answer_status: evaluation.answer_status,
          supplement: pendingUnknown.supplement,
          related_slides: Array.from(
            new Set([
              ...pendingUnknown.relatedSlides,
              ...evaluation.related_slides,
            ]),
          ),
          rubric: evaluation.rubric,
          ...(pendingUnknown.speechMetrics
            ? { speech_metrics: pendingUnknown.speechMetrics }
            : {}),
          retry_question: currentState.question,
          retry_answer: studentAnswer,
          ...(speechMetrics
            ? { retry_speech_metrics: speechMetrics }
            : {}),
          final_explanation:
            evaluation.supplement
              ? evaluation.supplement
              : null,
          // 참고 답변은 재질문 기준으로 작성되므로 재질문의 자료 근거를 싣는다
          question_focus: currentState.questionFocus,
          expected_answer_points: currentState.expectedAnswerPoints,
        })
        pendingUnknownAttemptRef.current = null
      } else {
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
          supplement: null,
          related_slides: [],
          rubric: evaluation.rubric,
          ...(speechMetrics
            ? { speech_metrics: speechMetrics }
            : {}),
          question_focus: currentState.questionFocus,
          expected_answer_points: currentState.expectedAnswerPoints,
        })
      }

      if (action === 'ask_followup') {
        let followupContract: FollowupResponse = {
          followup: evaluation.followup,
          followup_question_type:
            evaluation.followup_question_type,
          followup_focus: evaluation.followup_focus,
          followup_expected_answer_points:
            evaluation.followup_expected_answer_points,
          followup_speech_term_aliases:
            evaluation.followup_speech_term_aliases,
        }

        // 새 백엔드는 평가를 먼저 반환한다. 구버전 백엔드가 꼬리질문을
        // 동봉한 경우에는 그 응답을 그대로 사용해 배포 순서도 허용한다.
        if (!followupContract.followup) {
          try {
            followupContract = await fetchFollowup({
              script,
              slides,
              personaId,
              rootQuestion: currentState.rootQuestion,
              rootQuestionType:
                currentState.rootQuestionType,
              question: currentState.question,
              questionType: currentState.questionType,
              questionRole: currentState.questionRole,
              questionFocus: currentState.questionFocus,
              contextSlides: currentState.contextSlides,
              expectedAnswerPoints:
                currentState.expectedAnswerPoints,
              answer: studentAnswer,
              turn: currentTurn,
              maxTurns,
              difficulty,
              field,
              language,
              termHints: evaluationTermHints,
              strengths: evaluation.strengths,
              gaps: evaluation.gaps,
              rubric: evaluation.rubric,
            })
          } catch (exception) {
            setError(
              exception instanceof Error
                ? exception.message
                : String(exception),
            )
            await advanceAfterCurrentQuestion(currentTurn)
            return
          }
        }

        if (!followupContract.followup) {
          await advanceAfterCurrentQuestion(currentTurn)
          return
        }

        const nextTurn = currentTurn + 1
        const followup = followupContract.followup

        // 꼬리질문은 앞선 답변의 심화·확장이어야 하며 단순 반복은 신규 기본 질문으로 대체
        if (
          nextTurn > maxTurns ||
          isNearDuplicateQuestion(followup, currentQuestionChainRef.current)
        ) {
          await advanceAfterCurrentQuestion(currentTurn)
          return
        }

        const followupType =
          followupContract.followup_question_type ??
          currentState.questionType
        setTurn(nextTurn)
        setQuestionState({
          ...currentState,
          question: followup,
          questionType: followupType,
          questionRole: 'followup',
          questionFocus:
            followupContract.followup_focus ||
            currentState.questionFocus,
          expectedAnswerPoints:
            followupContract
              .followup_expected_answer_points.length > 0
              ? followupContract
                  .followup_expected_answer_points
              : currentState.expectedAnswerPoints,
          speechTermAliases: mergeSpeechTermAliases(
            currentState.speechTermAliases,
            followupContract
              .followup_speech_term_aliases ?? [],
          ),
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
            <div className="flex flex-wrap items-center gap-2">
              <div className="text-base font-bold text-slate-800">
                {persona.name}
              </div>
              <span
                className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-semibold text-slate-600"
              >
                난이도 {DIFFICULTY_LABELS[difficulty]}
              </span>
            </div>
            <div className="text-sm text-slate-500">
              남은 질문 횟수 {remainingQuestionCount}회
              <span className="ml-1.5 text-xs text-slate-400">
                {readyForReport
                  ? '(모든 질문 완료)'
                  : isUnknownRetryQuestion
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

      {!voiceInputAvailable && (
        <div
          role="status"
          className="shrink-0 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-relaxed text-amber-900"
        >
          <span className="font-semibold">
            {isEnglish
              ? 'Voice input is unavailable; continue with text input.'
              : '음성 입력 없이 텍스트로 스파링을 진행합니다.'}
          </span>{' '}
          {isEnglish
            ? 'Speech recognition is not available in this browser.'
            : browserSupport.message ??
              '현재 환경에서는 음성 입력을 사용할 수 없습니다.'}
        </div>
      )}

      <div
        ref={scrollRef}
        aria-live="polite"
        className="flex min-h-0 flex-1 flex-col space-y-4 overflow-y-auto rounded-2xl border border-slate-200/80 bg-white p-4 shadow-sm sm:p-5"
      >
        {messages.map((message, index) => {
          const messagePersona = getPersona(message.personaId)

          if (message.role === 'tip') {
            return (
              <div key={index} className="flex justify-center">
                <div className="flex max-w-[92%] items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-relaxed text-amber-900 shadow-sm">
                  <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                  <span>{message.text}</span>
                </div>
              </div>
            )
          }

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

                  {message.supplement && (
                    <div className="rounded-lg border border-indigo-100 bg-white px-3.5 py-3">
                      <div className="mb-1.5 text-sm font-bold text-indigo-700">
                        {message.supplementTitle ?? '생각해 볼 기본 아이디어'}
                      </div>
                      <div className="whitespace-pre-wrap text-slate-700">
                        {message.supplement}
                      </div>
                    </div>
                  )}

                  {message.answerStatus === 'unknown' &&
                    message.learningNote && (
                      <div className="rounded-lg border border-amber-100 bg-amber-50 px-3.5 py-2.5 text-sm font-semibold text-amber-800">
                        {message.learningNote}
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
                          {`${axis} ${value}`}
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
              {isEnglish ? 'Thinking…' : '생각 중…'}
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
            {isEnglish ? 'Error' : '오류'}: {error}
          </div>
        )}

        {displayedMicError && !readyForReport && (
          <div className="rounded-xl border border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-700">
            {displayedMicError}
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
        <div className="sticky bottom-0 z-10 flex shrink-0 flex-col gap-2 rounded-2xl border border-slate-200/80 bg-white/95 p-2.5 shadow-lg backdrop-blur sm:p-3">
          {listening && (
            <div className="flex min-w-0 items-center gap-2 rounded-xl border border-rose-100 bg-rose-50 px-3.5 py-2.5 text-sm text-rose-700">
              <span className="inline-block h-2 w-2 shrink-0 animate-pulse rounded-full bg-rose-500" />
              <span className="shrink-0 font-semibold">
                {isEnglish ? 'Listening…' : '받아쓰는 중…'}
              </span>
              <span className="min-w-0 truncate text-slate-500">
                {interim || (isEnglish ? '(start speaking)' : '(말해 보세요)')}
              </span>
            </div>
          )}

          <div className="flex gap-2">
            {voiceInputAvailable && (
              <button
                type="button"
                data-testid="mic-btn"
                onClick={() => void handleMicToggle()}
                disabled={busy || !questionState}
                title={
                  listening
                    ? (isEnglish ? 'Stop dictation' : '받아쓰기 중지')
                    : (isEnglish ? 'Answer by voice (STT)' : '음성으로 답변 (STT)')
                }
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
              onChange={(event: React.ChangeEvent<HTMLTextAreaElement>) =>
                updateAnswer(event.target.value)
              }
              onKeyDown={onKeyDown}
              disabled={busy || !questionState}
              rows={2}
              placeholder={
                isEnglish
                  ? voiceInputAvailable
                    ? 'Type or speak your answer. (Enter to submit, Shift+Enter for a new line)'
                    : 'Type your answer. (Enter to submit, Shift+Enter for a new line)'
                  : voiceInputAvailable
                    ? '답변을 입력하거나 마이크로 말하세요. (Enter 전송, Shift+Enter 줄바꿈)'
                    : '답변을 입력하세요. (Enter 전송, Shift+Enter 줄바꿈)'
              }
              className="min-h-12 min-w-0 flex-1 resize-none rounded-xl border border-slate-200 bg-slate-50/50 px-3.5 py-3 text-base leading-relaxed text-slate-700 outline-none transition focus:border-indigo-500 focus:bg-white focus:ring-2 focus:ring-indigo-500 disabled:opacity-50 sm:px-4"
            />

            <button
              type="button"
              onClick={() => void submit()}
              disabled={
                busy ||
                !questionState ||
                (!answer.trim() && !listening)
              }
              aria-label={isEnglish ? 'Submit answer' : '답변 전송'}
              className="flex h-12 shrink-0 items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 text-base font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-40 sm:px-6"
            >
              <Send className="h-5 w-5" />
              <span className="hidden sm:inline">
                {isEnglish ? 'Answer' : '답변'}
              </span>
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
