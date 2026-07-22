import type {
  SpeechMetricConfidence,
  SpeechMetrics,
} from '../types'

export interface RmsFrame {
  elapsed_ms: number
  rms: number
}

export interface CapturedSpeechSegment {
  duration_ms: number
  frames: RmsFrame[]
}

interface AnalyzedSegment {
  capturedDurationMs: number
  voicedDurationMs: number
  initialLatencyMs: number | null
  internalPausesMs: number[]
  volumeVariationDb: number | null
  confidence: SpeechMetricConfidence
  confidenceReasons: string[]
}

export const SPEECH_METRIC_CONFIG = {
  frameIntervalMs: 50,
  minVoiceRunMs: 150,
  minInternalPauseMs: 600,
  longPauseMs: 1500,
  minVoicedDurationForPaceMs: 4000,
  minWordsForPace: 5,
  minimumDynamicRangeDb: 6,
} as const

const EPSILON = 1e-7

/** 파형 배열의 RMS 계산. */
export function calculateRms(samples: Float32Array): number {
  if (samples.length === 0) return 0

  let squareSum = 0
  for (const sample of samples) {
    squareSum += sample * sample
  }

  return Math.sqrt(squareSum / samples.length)
}

/** 정렬된 수치 배열의 분위수 계산. */
function percentile(values: number[], ratio: number): number {
  if (values.length === 0) return 0

  const sorted = [...values].sort((left, right) => left - right)
  const position = Math.min(
    sorted.length - 1,
    Math.max(0, (sorted.length - 1) * ratio),
  )
  const lower = Math.floor(position)
  const upper = Math.ceil(position)

  if (lower === upper) return sorted[lower]

  const weight = position - lower
  return sorted[lower] * (1 - weight) + sorted[upper] * weight
}

/** 두 RMS 값 사이의 데시벨 차이 계산. */
function ratioToDb(high: number, low: number): number {
  return 20 * Math.log10((high + EPSILON) / (low + EPSILON))
}

/** 너무 짧은 발화 판정 구간 제거. */
function removeShortVoiceRuns(
  voicedFrames: boolean[],
  minFrameCount: number,
): boolean[] {
  const cleaned = [...voicedFrames]
  let index = 0

  while (index < cleaned.length) {
    if (!cleaned[index]) {
      index += 1
      continue
    }

    const start = index
    while (index < cleaned.length && cleaned[index]) {
      index += 1
    }

    if (index - start < minFrameCount) {
      for (let target = start; target < index; target += 1) {
        cleaned[target] = false
      }
    }
  }

  return cleaned
}

/** 인접 프레임 간 대표 시간 간격 계산. */
function resolveFrameDuration(
  frames: RmsFrame[],
  index: number,
): number {
  if (index + 1 < frames.length) {
    return Math.max(
      1,
      frames[index + 1].elapsed_ms - frames[index].elapsed_ms,
    )
  }

  return SPEECH_METRIC_CONFIG.frameIntervalMs
}

/** 단일 마이크 구간의 VAD 및 멈춤 분석. */
function analyzeSegment(
  segment: CapturedSpeechSegment,
): AnalyzedSegment {
  const frames = segment.frames
    .filter(
      (frame) =>
        Number.isFinite(frame.elapsed_ms) &&
        Number.isFinite(frame.rms) &&
        frame.elapsed_ms >= 0 &&
        frame.rms >= 0,
    )
    .sort((left, right) => left.elapsed_ms - right.elapsed_ms)

  const capturedDurationMs = Math.max(0, Math.round(segment.duration_ms))
  const reasons: string[] = []

  if (frames.length < 4 || capturedDurationMs < 200) {
    return {
      capturedDurationMs,
      voicedDurationMs: 0,
      initialLatencyMs: null,
      internalPausesMs: [],
      volumeVariationDb: null,
      confidence: 'low',
      confidenceReasons: ['분석 가능한 음성 프레임 부족'],
    }
  }

  const rmsValues = frames.map((frame) => frame.rms)
  const noiseFloor = percentile(rmsValues, 0.05)
  const speechLevel = percentile(rmsValues, 0.85)
  const dynamicRange = Math.max(0, speechLevel - noiseFloor)
  const dynamicRangeDb = ratioToDb(speechLevel, noiseFloor)

  if (dynamicRangeDb < SPEECH_METRIC_CONFIG.minimumDynamicRangeDb) {
    reasons.push('배경 소음과 발화 음량의 구분 부족')
  }

  const enterThreshold = Math.max(
    noiseFloor + dynamicRange * 0.35,
    noiseFloor * 1.8,
  )
  const exitThreshold = Math.max(
    noiseFloor + dynamicRange * 0.2,
    noiseFloor * 1.35,
  )

  let inVoice = false
  const medianRms = percentile(rmsValues, 0.5)
  const continuousVoiceFallback =
    dynamicRangeDb < SPEECH_METRIC_CONFIG.minimumDynamicRangeDb &&
    medianRms >= 0.01

  const rawVoicedFrames = continuousVoiceFallback
    ? frames.map(() => true)
    : frames.map((frame) => {
        if (inVoice) {
          if (frame.rms < exitThreshold) inVoice = false
        } else if (frame.rms >= enterThreshold) {
          inVoice = true
        }

        return inVoice
      })

  const minimumVoiceFrames = Math.max(
    1,
    Math.ceil(
      SPEECH_METRIC_CONFIG.minVoiceRunMs /
        SPEECH_METRIC_CONFIG.frameIntervalMs,
    ),
  )
  const voicedFrames = removeShortVoiceRuns(
    rawVoicedFrames,
    minimumVoiceFrames,
  )

  const firstVoicedIndex = voicedFrames.findIndex(Boolean)
  const lastVoicedIndex = voicedFrames.lastIndexOf(true)

  if (firstVoicedIndex < 0 || lastVoicedIndex < 0) {
    return {
      capturedDurationMs,
      voicedDurationMs: 0,
      initialLatencyMs: null,
      internalPausesMs: [],
      volumeVariationDb: null,
      confidence: 'low',
      confidenceReasons: [
        ...reasons,
        '유효 발화 구간 미검출',
      ],
    }
  }

  let voicedDurationMs = 0
  for (let index = 0; index < frames.length; index += 1) {
    if (voicedFrames[index]) {
      voicedDurationMs += resolveFrameDuration(frames, index)
    }
  }

  const internalPausesMs: number[] = []
  let pauseStartIndex: number | null = null

  for (
    let index = firstVoicedIndex + 1;
    index < lastVoicedIndex;
    index += 1
  ) {
    if (!voicedFrames[index] && pauseStartIndex == null) {
      pauseStartIndex = index
      continue
    }

    if (voicedFrames[index] && pauseStartIndex != null) {
      const pauseStart = frames[pauseStartIndex].elapsed_ms
      const pauseEnd = frames[index].elapsed_ms
      const pauseDuration = Math.max(0, pauseEnd - pauseStart)

      if (pauseDuration >= SPEECH_METRIC_CONFIG.minInternalPauseMs) {
        internalPausesMs.push(Math.round(pauseDuration))
      }

      pauseStartIndex = null
    }
  }

  const voicedRmsValues = frames
    .filter((_, index) => voicedFrames[index])
    .map((frame) => frame.rms)

  const volumeVariationDb =
    voicedRmsValues.length >= 4
      ? ratioToDb(
          percentile(voicedRmsValues, 0.9),
          percentile(voicedRmsValues, 0.1),
        )
      : null

  if (voicedDurationMs < 1000) {
    reasons.push('유효 발화 시간이 1초 미만')
  }

  const confidence: SpeechMetricConfidence =
    voicedDurationMs < 1000
      ? 'low'
      : continuousVoiceFallback ||
          voicedDurationMs <
            SPEECH_METRIC_CONFIG.minVoicedDurationForPaceMs
        ? 'medium'
        : 'high'

  if (
    confidence === 'medium' &&
    !reasons.includes('유효 발화 시간이 1초 미만')
  ) {
    reasons.push('말 빠르기 판단에 필요한 발화 시간 부족')
  }

  return {
    capturedDurationMs,
    voicedDurationMs: Math.round(voicedDurationMs),
    initialLatencyMs: Math.round(frames[firstVoicedIndex].elapsed_ms),
    internalPausesMs,
    volumeVariationDb:
      volumeVariationDb == null
        ? null
        : Number(volumeVariationDb.toFixed(1)),
    confidence,
    confidenceReasons: reasons,
  }
}

/** 한국어 답변의 공백 기준 어절 수 계산. */
export function countSttWords(text: string): number {
  return text.trim() ? text.trim().split(/\s+/).length : 0
}

/** STT 문자열에서 강한 필러의 인식 하한선 계산. */
export function countRecognizedFillers(text: string): number {
  const matches = text.match(
    /(?:^|[\s,.!?…])(?:어+|음+|으+음+)(?=$|[\s,.!?…])/g,
  )

  return matches?.length ?? 0
}

/** 음성 원문과 제출 답변을 이용한 혼합 입력 여부 판정. */
function resolveInputMode(
  sttWordCount: number,
  finalAnswerText: string,
): 'speech' | 'mixed' {
  const finalWordCount = countSttWords(finalAnswerText)

  return finalWordCount > sttWordCount * 1.25 + 2
    ? 'mixed'
    : 'speech'
}

/** 답변 하나의 다중 마이크 구간 합산. */
export function buildSpeechMetrics(
  segments: CapturedSpeechSegment[],
  rawFinalSttText: string,
  finalAnswerText: string,
  recognizedFillerMinimum = 0,
): SpeechMetrics | null {
  if (segments.length === 0) return null

  const analyzed = segments.map(analyzeSegment)
  const capturedDurationMs = analyzed.reduce(
    (sum, segment) => sum + segment.capturedDurationMs,
    0,
  )
  const voicedDurationMs = analyzed.reduce(
    (sum, segment) => sum + segment.voicedDurationMs,
    0,
  )
  const sttWordCount = countSttWords(rawFinalSttText)
  const internalPauses = analyzed.flatMap(
    (segment) => segment.internalPausesMs,
  )
  const firstVoicedSegment = analyzed.find(
    (segment) => segment.initialLatencyMs != null,
  )

  const weightedVolumeSum = analyzed.reduce((sum, segment) => {
    if (
      segment.volumeVariationDb == null ||
      segment.voicedDurationMs <= 0
    ) {
      return sum
    }

    return (
      sum +
      segment.volumeVariationDb * segment.voicedDurationMs
    )
  }, 0)
  const weightedVolumeDuration = analyzed.reduce((sum, segment) => {
    return segment.volumeVariationDb == null
      ? sum
      : sum + segment.voicedDurationMs
  }, 0)

  const confidenceReasons = Array.from(
    new Set(
      analyzed.flatMap((segment) => segment.confidenceReasons),
    ),
  )

  let confidence: SpeechMetricConfidence = 'high'
  if (voicedDurationMs < 1000) {
    confidence = 'low'
  } else if (
    analyzed.some((segment) => segment.confidence === 'low') ||
    voicedDurationMs <
      SPEECH_METRIC_CONFIG.minVoicedDurationForPaceMs
  ) {
    confidence = 'medium'
  }

  const paceWpm =
    confidence !== 'low' &&
    voicedDurationMs >=
      SPEECH_METRIC_CONFIG.minVoicedDurationForPaceMs &&
    sttWordCount >= SPEECH_METRIC_CONFIG.minWordsForPace
      ? Number(
          (
            sttWordCount /
            (voicedDurationMs / 60_000)
          ).toFixed(1),
        )
      : null

  if (
    paceWpm == null &&
    !confidenceReasons.includes(
      '말 빠르기 판단에 필요한 발화량 부족',
    )
  ) {
    confidenceReasons.push(
      '말 빠르기 판단에 필요한 발화량 부족',
    )
  }

  return {
    input_mode: resolveInputMode(
      sttWordCount,
      finalAnswerText,
    ),
    segment_count: segments.length,
    captured_duration_ms: capturedDurationMs,
    voiced_duration_ms: voicedDurationMs,
    initial_response_latency_ms:
      firstVoicedSegment?.initialLatencyMs ?? null,
    stt_word_count: sttWordCount,
    pace_wpm: paceWpm,
    internal_pause_count: internalPauses.length,
    long_pause_count: internalPauses.filter(
      (duration) =>
        duration >= SPEECH_METRIC_CONFIG.longPauseMs,
    ).length,
    longest_pause_ms:
      internalPauses.length > 0
        ? Math.max(...internalPauses)
        : null,
    volume_variation_db:
      weightedVolumeDuration > 0
        ? Number(
            (
              weightedVolumeSum /
              weightedVolumeDuration
            ).toFixed(1),
          )
        : null,
    recognized_filler_count: Math.max(
      countRecognizedFillers(rawFinalSttText),
      Math.max(0, Math.floor(recognizedFillerMinimum)),
    ),
    filler_measurement: 'recognized_minimum',
    confidence,
    confidence_reasons: confidenceReasons,
  }
}