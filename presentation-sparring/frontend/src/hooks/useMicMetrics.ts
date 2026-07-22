import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'
import {
  buildSpeechMetrics,
  calculateRms,
  SPEECH_METRIC_CONFIG,
} from '../lib/speechMetrics'
import type {
  CapturedSpeechSegment,
  RmsFrame,
} from '../lib/speechMetrics'
import type { SpeechMetrics } from '../types'

interface BrowserWindow extends Window {
  webkitAudioContext?: typeof AudioContext
}

interface ActiveSegment {
  startedAtMs: number
  frames: RmsFrame[]
}

interface LiveSilenceState {
  noiseFloorRms: number
  silenceStartedAtMs: number
}

interface UseMicMetricsResult {
  available: boolean
  recording: boolean
  error: string | null

  /** 마이크 시작 또는 마지막 발화 이후 5초 이상 침묵 시 증가 신호. */
  longSilenceSignal: number
  startUserSegment: () => Promise<boolean>
  stopUserSegment: () => void
  finalizeAnswer: (
    rawFinalSttText: string,
    finalAnswerText: string,
    recognizedFillerMinimum: number,
  ) => SpeechMetrics | null
  resetAnswer: () => void
}

/** 브라우저 AudioContext 생성자 조회. */
function getAudioContextConstructor(): typeof AudioContext | null {
  const browserWindow = window as BrowserWindow
  return (
    window.AudioContext ??
    browserWindow.webkitAudioContext ??
    null
  )
}

/** 답변별 RMS 프레임 수집 훅. */
export function useMicMetrics(): UseMicMetricsResult {
  const [available] = useState(
    () =>
      Boolean(navigator.mediaDevices?.getUserMedia) &&
      getAudioContextConstructor() !== null,
  )
  const [recording, setRecording] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [longSilenceSignal, setLongSilenceSignal] = useState(0)

  const streamRef = useRef<MediaStream | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const sourceRef =
    useRef<MediaStreamAudioSourceNode | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const sampleBufferRef = useRef<Float32Array<ArrayBuffer> | null>(null)
  const intervalRef = useRef<number | null>(null)
  const activeSegmentRef = useRef<ActiveSegment | null>(null)
  const completedSegmentsRef =
    useRef<CapturedSpeechSegment[]>([])
  const liveSilenceStateRef = useRef<LiveSilenceState>({
    noiseFloorRms: 0.003,
    silenceStartedAtMs: 0,
  })
  const longSilenceTipShownRef = useRef(false)

  /** RMS 수집 타이머 정리. */
  const clearSamplingInterval = useCallback(() => {
    if (intervalRef.current == null) return
    window.clearInterval(intervalRef.current)
    intervalRef.current = null
  }, [])

  /** 마이크 권한 및 AudioContext 파이프라인 초기화. */
  const ensureAudioPipeline =
    useCallback(async (): Promise<boolean> => {
      if (
        streamRef.current &&
        audioContextRef.current &&
        analyserRef.current
      ) {
        return true
      }

      const AudioContextConstructor =
        getAudioContextConstructor()
      if (
        !AudioContextConstructor ||
        !navigator.mediaDevices?.getUserMedia
      ) {
        setError(
          '현재 브라우저에서 음성 분석 기능을 사용할 수 없습니다.',
        )
        return false
      }

      try {
        const stream =
          await navigator.mediaDevices.getUserMedia({
            audio: {
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true,
            },
          })
        const audioContext = new AudioContextConstructor()
        const source =
          audioContext.createMediaStreamSource(stream)
        const analyser = audioContext.createAnalyser()

        analyser.fftSize = 2048
        analyser.smoothingTimeConstant = 0
        source.connect(analyser)

        streamRef.current = stream
        audioContextRef.current = audioContext
        sourceRef.current = source
        analyserRef.current = analyser
        // Web Audio API가 요구하는 ArrayBuffer 기반 샘플 버퍼 생성
        const sampleArrayBuffer = new ArrayBuffer(
          analyser.fftSize * Float32Array.BYTES_PER_ELEMENT,
        )
        sampleBufferRef.current = new Float32Array(
          sampleArrayBuffer,
        )
        setError(null)
        return true
      } catch (caught) {
        const exception = caught as DOMException
        if (
          exception.name === 'NotAllowedError' ||
          exception.name === 'SecurityError'
        ) {
          setError(
            '마이크 권한이 차단되어 있습니다. Chrome 주소창의 마이크 아이콘에서 권한을 허용해 주세요.',
          )
        } else if (
          exception.name === 'NotFoundError' ||
          exception.name === 'DevicesNotFoundError'
        ) {
          setError(
            '마이크를 찾을 수 없습니다. 마이크 연결 상태를 확인해 주세요.',
          )
        } else {
          setError(
            '음성 분석용 마이크를 시작하지 못했습니다.',
          )
        }
        return false
      }
    }, [])

  /** 사용자 조작 기준 마이크 구간 시작. */
  const startUserSegment =
    useCallback(async (): Promise<boolean> => {
      if (activeSegmentRef.current) return true

      const initialized = await ensureAudioPipeline()
      if (!initialized) return false

      const audioContext = audioContextRef.current
      const analyser = analyserRef.current
      const sampleBuffer = sampleBufferRef.current
      if (!audioContext || !analyser || !sampleBuffer) {
        setError('음성 분석기가 초기화되지 않았습니다.')
        return false
      }

      if (audioContext.state === 'suspended') {
        await audioContext.resume()
      }

      const startedAtMs = performance.now()
      activeSegmentRef.current = {
        startedAtMs,
        frames: [],
      }
      liveSilenceStateRef.current = {
        noiseFloorRms: 0.003,
        silenceStartedAtMs: startedAtMs,
      }
      setRecording(true)

      intervalRef.current = window.setInterval(() => {
        const activeSegment = activeSegmentRef.current
        const currentAnalyser = analyserRef.current
        const currentBuffer = sampleBufferRef.current
        if (
          !activeSegment ||
          !currentAnalyser ||
          !currentBuffer
        ) {
          return
        }

        currentAnalyser.getFloatTimeDomainData(
          currentBuffer,
        )
        const sampledAtMs = performance.now()
        const rms = calculateRms(currentBuffer)

        activeSegment.frames.push({
          elapsed_ms: sampledAtMs - startedAtMs,
          rms,
        })

        const liveState = liveSilenceStateRef.current
        const voiceThreshold = Math.max(
          0.006,
          liveState.noiseFloorRms * 1.8,
        )
        const isVoiceFrame = rms >= voiceThreshold

        if (isVoiceFrame) {
          // 마지막 발화 프레임 기준 침묵 시작 시각 갱신
          liveState.silenceStartedAtMs = sampledAtMs
        } else {
          // 정적 환경 변화 반영을 위한 배경 소음 기준 완만한 보정
          liveState.noiseFloorRms =
            liveState.noiseFloorRms * 0.97 + rms * 0.03

          if (
            sampledAtMs - liveState.silenceStartedAtMs >= 5_000 &&
            !longSilenceTipShownRef.current
          ) {
            longSilenceTipShownRef.current = true
            setLongSilenceSignal((previous) => previous + 1)
          }
        }
      }, SPEECH_METRIC_CONFIG.frameIntervalMs)

      return true
    }, [ensureAudioPipeline])

  /** 사용자 조작 기준 마이크 구간 종료. */
  const stopUserSegment = useCallback(() => {
    const activeSegment = activeSegmentRef.current
    if (!activeSegment) return

    clearSamplingInterval()
    const durationMs = Math.max(
      0,
      performance.now() - activeSegment.startedAtMs,
    )

    completedSegmentsRef.current.push({
      duration_ms: Math.round(durationMs),
      frames: activeSegment.frames,
    })
    activeSegmentRef.current = null
    setRecording(false)
  }, [clearSamplingInterval])

  /** 현재 답변의 다중 마이크 구간 합산. */
  const finalizeAnswer = useCallback(
    (
      rawFinalSttText: string,
      finalAnswerText: string,
      recognizedFillerMinimum: number,
    ): SpeechMetrics | null => {
      stopUserSegment()

      const metrics = buildSpeechMetrics(
        completedSegmentsRef.current,
        rawFinalSttText,
        finalAnswerText,
        recognizedFillerMinimum,
      )
      completedSegmentsRef.current = []
      longSilenceTipShownRef.current = false
      return metrics
    },
    [stopUserSegment],
  )

  /** 현재 답변 음성 버퍼 폐기. */
  const resetAnswer = useCallback(() => {
    stopUserSegment()
    completedSegmentsRef.current = []
    activeSegmentRef.current = null
    longSilenceTipShownRef.current = false
    setRecording(false)
  }, [stopUserSegment])

  useEffect(() => {
    return () => {
      clearSamplingInterval()
      activeSegmentRef.current = null
      completedSegmentsRef.current = []

      try {
        sourceRef.current?.disconnect()
      } catch {
        // 이미 해제된 오디오 노드 무시
      }

      for (const track of streamRef.current?.getTracks() ?? []) {
        track.stop()
      }

      void audioContextRef.current?.close()
      sourceRef.current = null
      analyserRef.current = null
      audioContextRef.current = null
      streamRef.current = null
      sampleBufferRef.current = null
    }
  }, [clearSamplingInterval])

  return {
    available,
    recording,
    error,
    longSilenceSignal,
    startUserSegment,
    stopUserSegment,
    finalizeAnswer,
    resetAnswer,
  }
}