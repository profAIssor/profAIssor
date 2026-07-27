import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'
import {
  countRecognizedFillers,
  restoreObservedFillers,
} from '../lib/speechMetrics'

/** lib.dom에 포함되지 않은 Web Speech API 최소 타입. */
interface SpeechRecognitionAlternativeLike {
  transcript: string
  confidence?: number
}

interface SpeechRecognitionResultLike {
  0: SpeechRecognitionAlternativeLike
  length: number
  [index: number]: SpeechRecognitionAlternativeLike
  isFinal: boolean
}

interface SpeechRecognitionEventLike {
  resultIndex: number
  results: {
    length: number
    [index: number]: SpeechRecognitionResultLike
  }
}

interface SpeechRecognitionLike {
  lang: string
  continuous: boolean
  interimResults: boolean
  maxAlternatives?: number
  phrases?: unknown[]
  start: () => void
  stop: () => void
  abort?: () => void
  onresult:
    | ((event: SpeechRecognitionEventLike) => void)
    | null
  onerror: ((event: { error: string }) => void) | null
  onend: (() => void) | null
}

type SpeechRecognitionConstructor =
  new () => SpeechRecognitionLike

type SpeechRecognitionPhraseConstructor =
  new (phrase: string, boost?: number) => unknown

interface BrowserWindow extends Window {
  SpeechRecognition?: SpeechRecognitionConstructor
  webkitSpeechRecognition?: SpeechRecognitionConstructor
  SpeechRecognitionPhrase?: SpeechRecognitionPhraseConstructor
}

interface Options {
  lang?: string
  /** 현재 질문에 한정된 소수의 전문 용어. */
  contextPhrases?: string[]
  /** 확정된 STT 조각 전달. */
  onFinal: (text: string) => void
  /** 현재 interim STT 전달. */
  onInterim?: (text: string) => void
}

interface PendingFlush {
  promise: Promise<string>
  resolve: (text: string) => void
  timeoutId: number
}

interface SpeechRecognitionHook {
  supported: boolean
  listening: boolean
  micError: string | null
  start: () => boolean
  stop: () => void
  toggle: () => void

  /** 현재 답변의 마지막 final 결과까지 기다린 뒤 원본 STT 반환. */
  stopAndFlush: () => Promise<string>

  /** 현재 답변에서 누적된 원본 final STT 조회. */
  getTranscript: () => string

  /** final·interim 결과에서 중복 없이 확인된 필러 최소치 조회. */
  getRecognizedFillerMinimum: () => number

  /** 다음 답변을 위한 원본 final STT와 필러 버퍼 초기화. */
  resetTranscript: () => void
}

/** Web Speech API 생성자 조회. */
function getConstructor():
  | SpeechRecognitionConstructor
  | null {
  const browserWindow = window as BrowserWindow
  return (
    browserWindow.SpeechRecognition ??
    browserWindow.webkitSpeechRecognition ??
    null
  )
}

const FATAL_ERRORS = new Set([
  'not-allowed',
  'service-not-allowed',
  'audio-capture',
])

const FLUSH_TIMEOUT_MS = 3_000
const MAX_ALTERNATIVES = 3
const CONTEXT_PHRASE_BOOST = 4.0
const FILLER_PHRASE_BOOST = 3.0
const ALTERNATIVE_CONFIDENCE_MARGIN = 0.03
const FILLER_BIAS_PHRASES = ['어', '음', '으음'] as const

const ERROR_MESSAGES: Record<string, string> = {
  'not-allowed':
    '마이크 권한이 차단되어 있습니다. Chrome 주소창의 마이크 아이콘에서 권한을 허용해 주세요.',
  'service-not-allowed':
    '마이크 권한이 차단되어 있습니다. Chrome 주소창의 마이크 아이콘에서 권한을 허용해 주세요.',
  'audio-capture':
    '마이크를 찾을 수 없습니다. 마이크가 연결되어 있는지 확인해 주세요.',
  network:
    '음성 인식 서비스에 연결할 수 없습니다. 네트워크 상태를 확인해 주세요.',
}

function normalizeForMatch(text: string): string {
  return text
    .normalize('NFKC')
    .toLowerCase()
    .replace(/[^a-z0-9가-힣]+/g, ' ')
    .trim()
    .replace(/\s+/g, ' ')
}

function countContextMatches(
  transcript: string,
  normalizedPhrases: string[],
): number {
  const normalizedTranscript = ` ${normalizeForMatch(transcript)} `
  return normalizedPhrases.reduce((count, phrase) => {
    return normalizedTranscript.includes(` ${phrase} `)
      ? count + 1
      : count
  }, 0)
}

/**
 * 엔진 1순위를 기본으로 유지하고, 거의 같은 confidence의 대안이 현재
 * 전문 용어 또는 실제 필러를 더 잘 보존할 때만 선택한다.
 */
function selectAlternative(
  result: SpeechRecognitionResultLike,
  contextPhrases: string[],
): string {
  const primary = result[0]
  if (!result.isFinal || result.length < 2) {
    return primary.transcript
  }

  const primaryConfidence = primary.confidence
  if (
    typeof primaryConfidence !== 'number' ||
    !Number.isFinite(primaryConfidence) ||
    primaryConfidence <= 0
  ) {
    return primary.transcript
  }

  const normalizedPhrases = contextPhrases
    .map(normalizeForMatch)
    .filter(Boolean)

  let selected = primary
  let selectedMatchCount = countContextMatches(
    primary.transcript,
    normalizedPhrases,
  )
  let selectedFillerCount =
    countRecognizedFillers(primary.transcript)

  for (let index = 1; index < result.length; index += 1) {
    const alternative = result[index]
    const confidence = alternative.confidence
    if (
      typeof confidence !== 'number' ||
      !Number.isFinite(confidence) ||
      confidence <
        primaryConfidence - ALTERNATIVE_CONFIDENCE_MARGIN
    ) {
      continue
    }

    const matchCount = countContextMatches(
      alternative.transcript,
      normalizedPhrases,
    )
    const fillerCount =
      countRecognizedFillers(alternative.transcript)
    if (
      matchCount > selectedMatchCount ||
      (
        matchCount === selectedMatchCount &&
        fillerCount > selectedFillerCount
      )
    ) {
      selected = alternative
      selectedMatchCount = matchCount
      selectedFillerCount = fillerCount
    }
  }

  return selected.transcript
}

/** 이미 확정된 문장 끝과 겹치는 interim 앞부분을 제거한다. */
function removeLeadingOverlap(
  existing: string,
  interim: string,
): string {
  const existingWords = existing.trim().split(/\s+/).filter(Boolean)
  const interimWords = interim.trim().split(/\s+/).filter(Boolean)
  const maximumOverlap = Math.min(
    existingWords.length,
    interimWords.length,
  )

  for (let size = maximumOverlap; size > 0; size -= 1) {
    const existingTail = normalizeForMatch(
      existingWords.slice(-size).join(' '),
    )
    const interimHead = normalizeForMatch(
      interimWords.slice(0, size).join(' '),
    )
    if (existingTail === interimHead) {
      return interimWords.slice(size).join(' ')
    }
  }

  return interimWords.join(' ')
}

/** 답변 입력용 Web Speech API 관리 훅. */
export function useSpeechRecognition({
  lang = 'ko-KR',
  contextPhrases = [],
  onFinal,
  onInterim,
}: Options): SpeechRecognitionHook {
  const [supported] = useState(
    () => getConstructor() !== null,
  )
  const [listening, setListening] = useState(false)
  const [micError, setMicError] =
    useState<string | null>(null)

  const recognitionRef =
    useRef<SpeechRecognitionLike | null>(null)
  const shouldListenRef = useRef(false)
  const listeningRef = useRef(false)
  const ignoreResultsRef = useRef(false)
  const answerTranscriptRef = useRef('')
  const latestInterimRef = useRef('')
  const answerFillerMinimumRef = useRef(0)
  const activeFillerMaxByResultRef =
    useRef<Map<number, number>>(new Map())
  const activeFillerTextByResultRef =
    useRef<Map<number, string>>(new Map())
  const committedResultIndicesRef =
    useRef<Set<number>>(new Set())
  const pendingFlushRef =
    useRef<PendingFlush | null>(null)
  const phrasesDisabledRef = useRef(false)
  const phraseFallbackAttemptedRef = useRef(false)

  const onFinalRef = useRef(onFinal)
  const onInterimRef = useRef(onInterim)
  onFinalRef.current = onFinal
  onInterimRef.current = onInterim

  /** final이 되지 못한 마지막 interim만 겹침 없이 보존. */
  const commitInterimFallback = useCallback(() => {
    const interim = latestInterimRef.current.trim()
    latestInterimRef.current = ''
    if (!interim) return

    const addition = removeLeadingOverlap(
      answerTranscriptRef.current,
      interim,
    )
    if (!addition) return

    answerTranscriptRef.current = answerTranscriptRef.current.trim()
      ? `${answerTranscriptRef.current.trimEnd()} ${addition}`
      : addition
    onFinalRef.current(addition)
  }, [])

  /** 현재 Chrome 인식 주기의 미확정 interim 필러 최소치 확정. */
  const commitRecognitionCycle = useCallback(() => {
    for (const [index, count] of activeFillerMaxByResultRef.current) {
      if (committedResultIndicesRef.current.has(index)) continue
      answerFillerMinimumRef.current += count
    }

    activeFillerMaxByResultRef.current.clear()
    activeFillerTextByResultRef.current.clear()
    committedResultIndicesRef.current.clear()
  }, [])

  /** 누적 STT 반환 및 flush 대기 해제. */
  const resolvePendingFlush = useCallback(() => {
    const pending = pendingFlushRef.current
    if (!pending) return

    window.clearTimeout(pending.timeoutId)
    pendingFlushRef.current = null
    pending.resolve(answerTranscriptRef.current.trim())
  }, [])

  // contextPhrases는 인식 인스턴스를 만들 때만 적용할 수 있습니다.
  // 호출부는 한 답변을 녹음하는 동안 동일한 배열을 유지하고,
  // 질문 전환 뒤 녹음이 멈춘 상태에서만 새 배열을 전달해야 합니다.
  useEffect(() => {
    const Constructor = getConstructor()
    if (!Constructor) return

    const recognition = new Constructor()
    recognition.lang = lang
    recognition.continuous = true
    recognition.interimResults = true
    if ('maxAlternatives' in recognition) {
      recognition.maxAlternatives = MAX_ALTERNATIVES
    }

    const browserWindow = window as BrowserWindow
    const PhraseConstructor =
      browserWindow.SpeechRecognitionPhrase
    if (
      !phrasesDisabledRef.current &&
      PhraseConstructor &&
      'phrases' in recognition
    ) {
      try {
        recognition.phrases = [
          ...contextPhrases.map(
            (phrase) =>
              new PhraseConstructor(
                phrase,
                CONTEXT_PHRASE_BOOST,
              ),
          ),
          ...FILLER_BIAS_PHRASES.map(
            (phrase) =>
              new PhraseConstructor(
                phrase,
                FILLER_PHRASE_BOOST,
              ),
          ),
        ]
      } catch {
        phrasesDisabledRef.current = true
        recognition.phrases = []
      }
    }

    recognition.onresult = (event) => {
      if (ignoreResultsRef.current) return

      let interim = ''

      for (
        let index = event.resultIndex;
        index < event.results.length;
        index += 1
      ) {
        const result = event.results[index]
        const recognizedText = selectAlternative(
          result,
          contextPhrases,
        ).trim()
        const currentFillerCount =
          countRecognizedFillers(recognizedText)
        const previousMaximum =
          activeFillerMaxByResultRef.current.get(index) ?? 0
        const observedMaximum = Math.max(
          previousMaximum,
          currentFillerCount,
        )
        const previousFillerText =
          activeFillerTextByResultRef.current.get(index) ?? ''

        activeFillerMaxByResultRef.current.set(
          index,
          observedMaximum,
        )
        if (
          currentFillerCount > 0 &&
          currentFillerCount >=
            countRecognizedFillers(previousFillerText)
        ) {
          activeFillerTextByResultRef.current.set(
            index,
            recognizedText,
          )
        }

        if (result.isFinal) {
          if (
            !committedResultIndicesRef.current.has(index)
          ) {
            answerFillerMinimumRef.current += observedMaximum
            committedResultIndicesRef.current.add(index)
          }
          activeFillerMaxByResultRef.current.delete(index)
          const finalText = restoreObservedFillers(
            recognizedText,
            activeFillerTextByResultRef.current.get(index) ?? '',
          )
          activeFillerTextByResultRef.current.delete(index)

          if (!finalText) continue

          answerTranscriptRef.current = (
            answerTranscriptRef.current.trim()
              ? `${answerTranscriptRef.current.trimEnd()} ${finalText}`
              : finalText
          )
          onFinalRef.current(finalText)
        } else if (recognizedText) {
          interim += `${recognizedText} `
        }
      }

      latestInterimRef.current = interim.trim()
      onInterimRef.current?.(latestInterimRef.current)
    }

    recognition.onerror = (event) => {
      if (event.error === 'phrases-not-supported') {
        phrasesDisabledRef.current = true
        try {
          recognition.phrases = []
        } catch {
          // 미지원 모델의 phrase 목록 해제 실패 무시
        }

        if (!phraseFallbackAttemptedRef.current) {
          phraseFallbackAttemptedRef.current = true
          return
        }

        shouldListenRef.current = false
        return
      }

      if (FATAL_ERRORS.has(event.error)) {
        shouldListenRef.current = false
      }

      const message = ERROR_MESSAGES[event.error]
      if (message) setMicError(message)
    }

    recognition.onend = () => {
      commitRecognitionCycle()
      // 브라우저가 continuous 세션을 자동으로 끊은 경우에도
      // 다음 세션이 같은 result index로 덮어쓰기 전에 마지막 interim을 보존한다.
      commitInterimFallback()

      if (shouldListenRef.current) {
        try {
          recognition.start()
          listeningRef.current = true
          setListening(true)
        } catch {
          shouldListenRef.current = false
          listeningRef.current = false
          setListening(false)
          resolvePendingFlush()
        }
        return
      }

      listeningRef.current = false
      setListening(false)
      onInterimRef.current?.('')
      resolvePendingFlush()
    }

    recognitionRef.current = recognition

    return () => {
      shouldListenRef.current = false
      listeningRef.current = false

      recognition.onresult = null
      recognition.onerror = null
      recognition.onend = null

      try {
        recognition.stop()
      } catch {
        // 이미 종료된 음성인식 인스턴스 무시
      }

      recognitionRef.current = null
      resolvePendingFlush()
    }
  }, [
    commitInterimFallback,
    commitRecognitionCycle,
    contextPhrases,
    lang,
    resolvePendingFlush,
  ])

  /** 사용자 조작 기준 STT 시작. */
  const start = useCallback((): boolean => {
    const recognition = recognitionRef.current
    if (!recognition || shouldListenRef.current) {
      return false
    }

    setMicError(null)
    shouldListenRef.current = true
    phraseFallbackAttemptedRef.current = false

    try {
      recognition.start()
      ignoreResultsRef.current = false
      listeningRef.current = true
      setListening(true)
      return true
    } catch {
      shouldListenRef.current = false
      listeningRef.current = false
      setListening(false)
      return false
    }
  }, [])

  /** 마지막 final STT 수신까지 대기 후 종료. */
  const stopAndFlush =
    useCallback(async (): Promise<string> => {
      const recognition = recognitionRef.current
      shouldListenRef.current = false

      const existingFlush = pendingFlushRef.current
      if (existingFlush) {
        return existingFlush.promise
      }

      if (!recognition || !listeningRef.current) {
        listeningRef.current = false
        setListening(false)
        commitInterimFallback()
        return answerTranscriptRef.current.trim()
      }

      let resolvePromise:
        | ((text: string) => void)
        | null = null

      const promise = new Promise<string>((resolve) => {
        resolvePromise = resolve
      })

      const timeoutId = window.setTimeout(() => {
        listeningRef.current = false
        setListening(false)
        commitInterimFallback()
        // stop() 응답이 늦더라도 이전 답변의 결과가 reset 이후
        // 다음 질문으로 유입되지 않도록 이 인식 세션을 폐기한다.
        ignoreResultsRef.current = true
        try {
          recognition.abort?.()
        } catch {
          // 이미 종료된 인식 세션 무시
        }
        onInterimRef.current?.('')
        resolvePendingFlush()
      }, FLUSH_TIMEOUT_MS)

      pendingFlushRef.current = {
        promise,
        resolve: (text: string) => {
          resolvePromise?.(text)
        },
        timeoutId,
      }

      try {
        recognition.stop()
      } catch {
        commitInterimFallback()
        ignoreResultsRef.current = true
        try {
          recognition.abort?.()
        } catch {
          // 이미 종료된 인식 세션 무시
        }
        resolvePendingFlush()
      }

      return promise
    }, [commitInterimFallback, resolvePendingFlush])

  /** 대기 없이 STT 종료 요청. */
  const stop = useCallback(() => {
    void stopAndFlush()
  }, [stopAndFlush])

  /** 마이크 버튼 토글 처리. */
  const toggle = useCallback(() => {
    if (shouldListenRef.current) {
      stop()
      return
    }

    start()
  }, [start, stop])

  /** 현재 답변 원본 final STT 조회. */
  const getTranscript = useCallback(
    () => answerTranscriptRef.current.trim(),
    [],
  )

  /** 현재 답변에서 중복 없이 확인된 필러 최소치 조회. */
  const getRecognizedFillerMinimum = useCallback(
    () => {
      const activeMinimum = Array.from(
        activeFillerMaxByResultRef.current.entries(),
      ).reduce((sum, [index, count]) => {
        return committedResultIndicesRef.current.has(index)
          ? sum
          : sum + count
      }, 0)

      return answerFillerMinimumRef.current + activeMinimum
    },
    [],
  )

  /** 현재 답변 원본 final STT와 필러 버퍼 초기화. */
  const resetTranscript = useCallback(() => {
    answerTranscriptRef.current = ''
    latestInterimRef.current = ''
    answerFillerMinimumRef.current = 0
    activeFillerMaxByResultRef.current.clear()
    activeFillerTextByResultRef.current.clear()
    committedResultIndicesRef.current.clear()
    onInterimRef.current?.('')
  }, [])

  return {
    supported,
    listening,
    micError,
    start,
    stop,
    toggle,
    stopAndFlush,
    getTranscript,
    getRecognizedFillerMinimum,
    resetTranscript,
  }
}
