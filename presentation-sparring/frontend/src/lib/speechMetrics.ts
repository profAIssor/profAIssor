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
  articulationDurationMs: number
  initialLatencyMs: number | null
  internalPausesMs: number[]
  volumeVariationDb: number | null
  confidence: SpeechMetricConfidence
  confidenceReasons: string[]
}

export const SPEECH_METRIC_CONFIG = {
  frameIntervalMs: 50,
  minVoiceRunMs: 150,
  minArticulationPauseMs: 250,
  minInternalPauseMs: 600,
  longPauseMs: 4000,
  liveSilenceTipMs: 5000,
  initialNoiseFloorRms: 0.003,
  minimumLiveVoiceRms: 0.006,
  liveVoiceNoiseMultiplier: 1.8,
  noiseFloorPreviousWeight: 0.97,
  noiseFloorSampleWeight: 0.03,
  minVoicedDurationForAnalysisMs: 4000,
  minArticulationDurationForPaceMs: 5000,
  minSyllablesForPace: 20,
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
      articulationDurationMs: 0,
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
      articulationDurationMs: 0,
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

  const articulationPausesMs: number[] = []
  const internalPausesMs: number[] = []
  let pauseStartIndex: number | null = null

  for (
    let index = firstVoicedIndex + 1;
    index <= lastVoicedIndex;
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

      if (
        pauseDuration >=
        SPEECH_METRIC_CONFIG.minArticulationPauseMs
      ) {
        articulationPausesMs.push(Math.round(pauseDuration))
      }

      if (pauseDuration >= SPEECH_METRIC_CONFIG.minInternalPauseMs) {
        internalPausesMs.push(Math.round(pauseDuration))
      }

      pauseStartIndex = null
    }
  }

  const speechSpanEndMs = Math.min(
    capturedDurationMs,
    frames[lastVoicedIndex].elapsed_ms +
      resolveFrameDuration(frames, lastVoicedIndex),
  )
  const speechSpanDurationMs = Math.max(
    0,
    speechSpanEndMs - frames[firstVoicedIndex].elapsed_ms,
  )
  const articulationDurationMs = Math.max(
    0,
    speechSpanDurationMs -
      articulationPausesMs.reduce(
        (sum, duration) => sum + duration,
        0,
      ),
  )

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
            SPEECH_METRIC_CONFIG.minVoicedDurationForAnalysisMs
        ? 'medium'
        : 'high'

  if (
    confidence === 'medium' &&
    !reasons.includes('유효 발화 시간이 1초 미만')
  ) {
    reasons.push('음성 분석에 필요한 유효 발화 시간 부족')
  }

  return {
    capturedDurationMs,
    voicedDurationMs: Math.min(
      capturedDurationMs,
      Math.round(voicedDurationMs),
    ),
    articulationDurationMs: Math.min(
      capturedDurationMs,
      Math.round(articulationDurationMs),
    ),
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

/** 한국어 발표 속도 판정을 위한 음절 수를 계산합니다. */
export function countSttSyllables(text: string): number {
  const normalized = text.normalize('NFKC')
  const hangulCount = normalized.match(/[가-힣]/g)?.length ?? 0
  const digitCount = normalized.match(/\d/g)?.length ?? 0
  const latinCount = (normalized.match(/[A-Za-z]+/g) ?? []).reduce(
    (sum, token) => {
      const vowelGroups = token.toLowerCase().match(/[aeiouy]+/g)
      return sum + Math.max(1, vowelGroups?.length ?? 0)
    },
    0,
  )

  return hangulCount + latinCount + digitCount
}

/** STT 문자열에서 강한 필러의 인식 하한선 계산. */
export function countRecognizedFillers(text: string): number {
  const matches = text.match(
    /(?:^|[\s,.!?…])(?:어+|음+|으+음+)(?=$|[\s,.!?…])/g,
  )

  return matches?.length ?? 0
}

interface SpeechToken {
  sourceIndex: number
  value: string
  normalized: string
  isFiller: boolean
}

function tokenizeSpeechText(text: string): SpeechToken[] {
  return text
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((value, sourceIndex) => {
      const normalized = value
        .normalize('NFKC')
        .toLowerCase()
        .replace(/^[,.!?…]+|[,.!?…]+$/g, '')

      return {
        sourceIndex,
        value,
        normalized,
        isFiller: /^(?:어+|음+|으+음+)$/.test(normalized),
      }
    })
}

/**
 * interim에서 실제로 확인된 필러가 final 정제 과정에서 빠졌다면,
 * 일치하는 주변 어절을 기준으로 원래 위치에 가깝게 복원합니다.
 * 관찰되지 않은 필러는 새로 만들지 않습니다.
 */
export function restoreObservedFillers(
  finalText: string,
  observedText: string,
): string {
  const finalTokens = tokenizeSpeechText(finalText)
  const observedTokens = tokenizeSpeechText(observedText)
  const observedFillers = observedTokens.filter(
    ({ isFiller }) => isFiller,
  )

  if (observedFillers.length === 0) return finalText
  if (finalTokens.length === 0) return observedText.trim()

  const finalFillerCount = finalTokens.filter(
    ({ isFiller }) => isFiller,
  ).length
  if (finalFillerCount >= observedFillers.length) {
    return finalText
  }

  const remainingFinalFillers = new Map<string, number>()
  for (const token of finalTokens) {
    if (!token.isFiller) continue
    remainingFinalFillers.set(
      token.normalized,
      (remainingFinalFillers.get(token.normalized) ?? 0) + 1,
    )
  }

  const requiredMissingCount =
    observedFillers.length - finalFillerCount
  const missingFillers = observedFillers
    .filter((token) => {
      const remaining =
        remainingFinalFillers.get(token.normalized) ?? 0
      if (remaining <= 0) return true
      remainingFinalFillers.set(token.normalized, remaining - 1)
      return false
    })
    .slice(0, requiredMissingCount)
  if (missingFillers.length === 0) return finalText

  const observedContentTokens = observedTokens.filter(
    ({ isFiller, normalized }) => !isFiller && normalized,
  )
  const finalContentTokens = finalTokens.filter(
    ({ isFiller, normalized }) => !isFiller && normalized,
  )
  const matchedFinalIndexByObservedIndex = new Map<number, number>()
  let finalSearchIndex = 0

  for (const observedToken of observedContentTokens) {
    const matchedOffset = finalContentTokens
      .slice(finalSearchIndex)
      .findIndex(
        ({ normalized }) =>
          normalized === observedToken.normalized,
      )
    if (matchedOffset < 0) continue

    const matchedIndex = finalSearchIndex + matchedOffset
    matchedFinalIndexByObservedIndex.set(
      observedToken.sourceIndex,
      finalContentTokens[matchedIndex].sourceIndex,
    )
    finalSearchIndex = matchedIndex + 1
  }

  const insertions = new Map<number, string[]>()
  for (const filler of missingFillers) {
    const previousMatches =
      [...matchedFinalIndexByObservedIndex].filter(
        ([observedIndex]) => observedIndex < filler.sourceIndex,
      )
    const previousMatch =
      previousMatches[previousMatches.length - 1]
    const nextMatch = [...matchedFinalIndexByObservedIndex].find(
      ([observedIndex]) => observedIndex > filler.sourceIndex,
    )
    const previousDistance = previousMatch
      ? filler.sourceIndex - previousMatch[0]
      : Number.POSITIVE_INFINITY
    const nextDistance = nextMatch
      ? nextMatch[0] - filler.sourceIndex
      : Number.POSITIVE_INFINITY
    const insertionIndex =
      previousMatch && previousDistance <= nextDistance
        ? previousMatch[1] + 1
        : (nextMatch?.[1] ?? 0)
    const values = insertions.get(insertionIndex) ?? []
    values.push(filler.value)
    insertions.set(insertionIndex, values)
  }

  const restored: string[] = []
  for (let index = 0; index <= finalTokens.length; index += 1) {
    restored.push(...(insertions.get(index) ?? []))
    if (index < finalTokens.length) {
      restored.push(finalTokens[index].value)
    }
  }

  return restored.join(' ')
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
  const voicedDurationMs = Math.min(
    capturedDurationMs,
    analyzed.reduce(
      (sum, segment) => sum + segment.voicedDurationMs,
      0,
    ),
  )
  const articulationDurationMs = Math.min(
    capturedDurationMs,
    analyzed.reduce(
      (sum, segment) => sum + segment.articulationDurationMs,
      0,
    ),
  )
  const sttWordCount = countSttWords(rawFinalSttText)
  const sttSyllableCount = countSttSyllables(rawFinalSttText)
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
      SPEECH_METRIC_CONFIG.minVoicedDurationForAnalysisMs
  ) {
    confidence = 'medium'
  }

  const paceWpm =
    confidence !== 'low' &&
    articulationDurationMs >=
      SPEECH_METRIC_CONFIG.minArticulationDurationForPaceMs &&
    sttSyllableCount >=
      SPEECH_METRIC_CONFIG.minSyllablesForPace
      ? Number(
          (
            sttWordCount /
            (articulationDurationMs / 60_000)
          ).toFixed(1),
        )
      : null

  const paceExclusionReason =
    '20음절 또는 조음 시간 5초 미만이라 속도 판정 제외'
  if (
    paceWpm == null &&
    !confidenceReasons.includes(paceExclusionReason)
  ) {
    confidenceReasons.push(paceExclusionReason)
  }

  return {
    input_mode: resolveInputMode(
      sttWordCount,
      finalAnswerText,
    ),
    segment_count: segments.length,
    captured_duration_ms: capturedDurationMs,
    voiced_duration_ms: voicedDurationMs,
    articulation_duration_ms: articulationDurationMs,
    initial_response_latency_ms:
      firstVoicedSegment?.initialLatencyMs ?? null,
    stt_word_count: sttWordCount,
    stt_syllable_count: sttSyllableCount,
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
