import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'
import { countRecognizedFillers } from '../lib/speechMetrics'

/** lib.dom에 포함되지 않은 Web Speech API 최소 타입. */
interface SpeechRecognitionResultLike {
  0: { transcript: string }
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
  start: () => void
  stop: () => void
  onresult:
    | ((event: SpeechRecognitionEventLike) => void)
    | null
  onerror: ((event: { error: string }) => void) | null
  onend: (() => void) | null
}

type SpeechRecognitionConstructor =
  new () => SpeechRecognitionLike

interface BrowserWindow extends Window {
  SpeechRecognition?: SpeechRecognitionConstructor
  webkitSpeechRecognition?: SpeechRecognitionConstructor
}

interface Options {
  lang?: string
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

/** 답변 입력용 Web Speech API 관리 훅. */
export function useSpeechRecognition({
  lang = 'ko-KR',
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
  const answerTranscriptRef = useRef('')
  const answerFillerMinimumRef = useRef(0)
  const activeFillerMaxByResultRef =
    useRef<Map<number, number>>(new Map())
  const committedResultIndicesRef =
    useRef<Set<number>>(new Set())
  const pendingFlushRef =
    useRef<PendingFlush | null>(null)

  const onFinalRef = useRef(onFinal)
  const onInterimRef = useRef(onInterim)
  onFinalRef.current = onFinal
  onInterimRef.current = onInterim

  /** 현재 Chrome 인식 주기의 미확정 interim 필러 최소치 확정. */
  const commitRecognitionCycle = useCallback(() => {
    for (const [index, count] of activeFillerMaxByResultRef.current) {
      if (committedResultIndicesRef.current.has(index)) continue
      answerFillerMinimumRef.current += count
    }

    activeFillerMaxByResultRef.current.clear()
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

  useEffect(() => {
    const Constructor = getConstructor()
    if (!Constructor) return

    const recognition = new Constructor()
    recognition.lang = lang
    recognition.continuous = true
    recognition.interimResults = true

    recognition.onresult = (event) => {
      let interim = ''

      for (
        let index = event.resultIndex;
        index < event.results.length;
        index += 1
      ) {
        const result = event.results[index]
        const recognizedText = result[0].transcript.trim()
        const currentFillerCount =
          countRecognizedFillers(recognizedText)
        const previousMaximum =
          activeFillerMaxByResultRef.current.get(index) ?? 0
        const observedMaximum = Math.max(
          previousMaximum,
          currentFillerCount,
        )

        activeFillerMaxByResultRef.current.set(
          index,
          observedMaximum,
        )

        if (result.isFinal) {
          if (
            !committedResultIndicesRef.current.has(index)
          ) {
            answerFillerMinimumRef.current += observedMaximum
            committedResultIndicesRef.current.add(index)
          }
          activeFillerMaxByResultRef.current.delete(index)

          if (!recognizedText) continue

          answerTranscriptRef.current = (
            answerTranscriptRef.current.trim()
              ? `${answerTranscriptRef.current.trimEnd()} ${recognizedText}`
              : recognizedText
          )
          onFinalRef.current(recognizedText)
        } else if (recognizedText) {
          interim += `${recognizedText} `
        }
      }

      onInterimRef.current?.(interim.trim())
    }

    recognition.onerror = (event) => {
      if (FATAL_ERRORS.has(event.error)) {
        shouldListenRef.current = false
      }

      const message = ERROR_MESSAGES[event.error]
      if (message) setMicError(message)
    }

    recognition.onend = () => {
      commitRecognitionCycle()

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
  }, [commitRecognitionCycle, lang, resolvePendingFlush])

  /** 사용자 조작 기준 STT 시작. */
  const start = useCallback((): boolean => {
    const recognition = recognitionRef.current
    if (!recognition || shouldListenRef.current) {
      return false
    }

    setMicError(null)
    shouldListenRef.current = true

    try {
      recognition.start()
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
      onInterimRef.current?.('')

      const existingFlush = pendingFlushRef.current
      if (existingFlush) {
        return existingFlush.promise
      }

      if (!recognition || !listeningRef.current) {
        listeningRef.current = false
        setListening(false)
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
        resolvePendingFlush()
      }

      return promise
    }, [resolvePendingFlush])

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
    answerFillerMinimumRef.current = 0
    activeFillerMaxByResultRef.current.clear()
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