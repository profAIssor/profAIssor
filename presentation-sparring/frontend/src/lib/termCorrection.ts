import { distance } from 'fastest-levenshtein'
import type { SpeechTermAlias } from '../types'

// Common Korean connectors/particles that show up in every script — never
// worth treating as a "term" to correct toward.
const STOPWORDS = new Set([
  '그리고', '그러나', '하지만', '또한', '때문', '위해', '대한', '통해', '있는', '있다',
  '합니다', '입니다', '이다', '및', '등',
])

const SPEECH_CONTEXT_STOPWORDS = new Set([
  ...STOPWORDS,
  '무엇인가요', '설명해주세요', '말씀해주세요', '어떻게', '이유는', '근거는',
  '관련하여', '대해서', '구체적인', '조건은', '경우에는', '발표에서',
])

// 2-char words are excluded: at that length any single-edit correction already
// exceeds MAX_EDIT_RATIO, but a 2-char word can still spuriously match a
// slightly longer dict term that has a particle attached (e.g. "오늘" vs
// "오늘은") because the ratio denominator uses the longer of the two lengths.
const MIN_WORD_LEN = 3
// How much of a word's length may differ (edit distance) and still count as
// "the same word, mis-transcribed". Kept low so we only fix plausible STT
// mishearings, never swap in an unrelated dictionary term.
const MAX_EDIT_RATIO = 0.25
const MAX_SPEECH_CONTEXT_PHRASES = 24
const MAX_CONTEXTUAL_SYLLABLE_RATIO = 0.45
const MAX_CONTEXTUAL_JAMO_RATIO = 0.3
const MAX_CONTEXTUAL_JAMO_DISTANCE = 4
const MAX_CONTEXTUAL_COMBINED_SCORE = 0.34
const MIN_CONTEXTUAL_CANONICAL_MARGIN = 0.06
const MAX_FILLERS_BETWEEN_TERM_PARTS = 4
const FILLER_TOKEN_PATTERN = /^(?:어+|음+|으+음+)$/

const KOREAN_PARTICLE_SUFFIXES = [
  '이었습니다',
  '였습니다',
  '이라고',
  '이라면',
  '입니까',
  '입니다',
  '이에요',
  '에서는',
  '으로는',
  '에게는',
  '처럼',
  '보다',
  '에서',
  '에게',
  '이고',
  '이며',
  '라는',
  '라면',
  '였다',
  '으로',
  '예요',
  '인가',
  '인',
  '은',
  '는',
  '이',
  '가',
  '을',
  '를',
  '과',
  '와',
  '의',
  '로',
  '만',
  '도',
] as const
const KOREAN_PARTICLE_LOOKAHEAD =
  `(?:${KOREAN_PARTICLE_SUFFIXES.join('|')})`

interface SpeechContextInput {
  question: string
  slides: { text: string }[]
}

interface SpeechCandidate {
  value: string
  categories: Set<'question' | 'slide'>
  order: number
}

function normalizeTerm(term: string): string {
  return term
    .normalize('NFKC')
    .toLowerCase()
    .replace(/[^a-z0-9가-힣+#./-]+/g, ' ')
    .trim()
    .replace(/\s+/g, ' ')
}

function scriptKind(term: string): string {
  return `${/[A-Za-z]/.test(term)}:${/[가-힣]/.test(term)}`
}

function extractSpeechCandidates(text: string): string[] {
  const englishPhrases =
    text.match(/[A-Za-z][A-Za-z0-9]*(?:[- ][A-Za-z][A-Za-z0-9]*){0,4}/g) ?? []
  const englishTerms = englishPhrases.flatMap(
    (phrase) =>
      phrase.match(/[A-Za-z][A-Za-z0-9-]*/g) ?? [],
  )
  const tokens =
    text.match(/[A-Za-z0-9가-힣][A-Za-z0-9가-힣+#./-]{2,}/g) ?? []

  return [...englishPhrases, ...englishTerms, ...tokens]
    .map((term) => term.trim())
    .filter((term) => term.length >= MIN_WORD_LEN)
    .filter((term) => !SPEECH_CONTEXT_STOPWORDS.has(normalizeTerm(term)))
}

/**
 * 현재 질문에서 실제로 등장할 가능성이 높은 소수의 전문 용어만 추린다.
 * 내부 채점 기준(expected answer points)은 음성 인식에 주입하지 않는다.
 */
export function buildSpeechContextPhrases({
  question,
  slides,
}: SpeechContextInput): string[] {
  const candidates = new Map<string, SpeechCandidate>()
  let order = 0

  const add = (
    text: string,
    category: 'question' | 'slide',
  ) => {
    for (const value of extractSpeechCandidates(text)) {
      const normalized = normalizeTerm(value)
      if (!normalized) continue

      const existing = candidates.get(normalized)
      if (existing) {
        existing.categories.add(category)
        continue
      }

      candidates.set(normalized, {
        value,
        categories: new Set([category]),
        order,
      })
      order += 1
    }
  }

  add(question, 'question')
  for (const slide of slides) add(slide.text, 'slide')

  return [...candidates.values()]
    .filter(({ value, categories }) => {
      return /[A-Za-z0-9]/.test(value) || categories.size >= 2
    })
    .sort((left, right) => {
      const leftTechnical = /[A-Za-z0-9]/.test(left.value) ? 1 : 0
      const rightTechnical = /[A-Za-z0-9]/.test(right.value) ? 1 : 0
      return (
        rightTechnical - leftTechnical ||
        right.categories.size - left.categories.size ||
        right.value.length - left.value.length ||
        left.order - right.order
      )
    })
    .slice(0, MAX_SPEECH_CONTEXT_PHRASES)
    .map(({ value }) => value)
}

/**
 * Candidate terms an STT engine is likely to mis-hear: everything in the
 * script + slide text except common particles/connectors.
 */
export function buildTermDictionary(script: string, slides: { text: string }[]): string[] {
  const source = script + '\n' + slides.map((s) => s.text).join('\n')
  const tokens = source.match(/[A-Za-z0-9가-힣]{2,}/g) ?? []
  const dict = new Set<string>()
  for (const t of tokens) {
    if (t.length < MIN_WORD_LEN || STOPWORDS.has(t)) continue
    dict.add(t)
  }
  return [...dict]
}

/** 질문 전환 시 기존 자료 용어와 새 질문의 동적 발음 사전을 병합합니다. */
export function mergeSpeechTermAliases(
  ...groups: SpeechTermAlias[][]
): SpeechTermAlias[] {
  const merged = new Map<string, SpeechTermAlias>()

  for (const entry of groups.flat()) {
    const canonical = entry.canonical.trim()
    const canonicalKey = normalizeTerm(canonical)
    if (!canonicalKey || !/[A-Za-z]/.test(canonical)) continue

    const existing = merged.get(canonicalKey)
    if (!existing) {
      merged.set(canonicalKey, {
        canonical,
        aliases: [...new Set(entry.aliases)],
      })
      continue
    }

    existing.aliases = [
      ...new Set([...existing.aliases, ...entry.aliases]),
    ]
  }

  return [...merged.values()]
}

interface ContextualPhoneticAlias {
  alias: string
  canonical: string
  canonicalKey: string
}

interface HangulToken {
  value: string
  start: number
  end: number
  filler: boolean
}

interface CanonicalComponents {
  values: string[]
  separators: string[]
}

interface FuzzyPronunciationMatch {
  canonicalKey: string
  start: number
  end: number
  endTokenIndex: number
  replacement: string
  score: number
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/**
 * 백엔드가 자료 원문과 대조한 동적 발음 사전을 한 번 더 검증합니다.
 * 같은 발음이 서로 다른 원문 용어를 가리키면 어느 쪽에도 적용하지 않습니다.
 */
function buildContextualPhoneticAliases(
  entries: SpeechTermAlias[],
): ContextualPhoneticAlias[] {
  const aliases = new Map<
    string,
    ContextualPhoneticAlias | null
  >()

  for (const entry of entries) {
    const canonical = entry.canonical.trim()
    if (
      !canonical ||
      !/[A-Za-z]/.test(canonical) ||
      !Array.isArray(entry.aliases)
    ) {
      continue
    }

    const canonicalKey = normalizeTerm(canonical)
    for (const rawAlias of entry.aliases) {
      const alias = rawAlias.trim().replace(/\s+/g, ' ')
      if (
        !alias ||
        !/^[가-힣 ]+$/.test(alias) ||
        // 실제 필러가 기술 용어로 치환되지 않도록 별칭 적용만 막습니다.
        // STT 원문과 화면의 필러는 useSpeechRecognition에서 그대로 보존됩니다.
        FILLER_TOKEN_PATTERN.test(alias.replace(/\s+/g, ''))
      ) {
        continue
      }

      const aliasKey = normalizeTerm(alias)
      const existing = aliases.get(aliasKey)

      if (
        existing &&
        existing.canonicalKey !== canonicalKey
      ) {
        aliases.set(aliasKey, null)
        continue
      }
      if (existing === null) continue

      aliases.set(aliasKey, {
        alias,
        canonical,
        canonicalKey,
      })
    }
  }

  return [...aliases.values()]
    .filter(
      (
        entry,
      ): entry is ContextualPhoneticAlias =>
        entry !== null,
    )
    .sort(
      (left, right) =>
        right.alias.length - left.alias.length,
    )
}

function applyExactContextualPronunciations(
  text: string,
  aliases: ContextualPhoneticAlias[],
): string {
  let corrected = text

  for (const { alias, canonical } of aliases) {
    const aliasPattern = alias
      .split(/\s+/)
      .map(escapeRegExp)
      .join('[\\s-]+')
    const pattern = new RegExp(
      `(^|[^A-Za-z0-9가-힣])${aliasPattern}` +
        `(?=$|[^A-Za-z0-9가-힣]|${KOREAN_PARTICLE_LOOKAHEAD})`,
      'gi',
    )
    corrected = corrected.replace(
      pattern,
      (_match, prefix: string) =>
        `${prefix}${canonical}`,
    )
  }

  return corrected
}

function extractHangulTokens(text: string): HangulToken[] {
  return [...text.matchAll(/[가-힣]+/g)].map((match) => {
    const value = match[0]
    const start = match.index ?? 0
    return {
      value,
      start,
      end: start + value.length,
      filler: FILLER_TOKEN_PATTERN.test(value),
    }
  })
}

function splitCanonicalComponents(
  canonical: string,
): CanonicalComponents {
  const matches = [
    ...canonical.matchAll(
      /[A-Za-z0-9]+(?:[+#./][A-Za-z0-9]+)*/g,
    ),
  ]
  const values = matches.map((match) => match[0])
  const separators: string[] = []

  for (let index = 1; index < matches.length; index += 1) {
    const previous = matches[index - 1]
    const current = matches[index]
    const previousStart = previous.index ?? 0
    const currentStart = current.index ?? 0
    separators.push(
      canonical.slice(
        previousStart + previous[0].length,
        currentStart,
      ),
    )
  }

  return { values, separators }
}

function particleVariants(
  values: string[],
): { values: string[]; suffix: string }[] {
  const variants = [{ values, suffix: '' }]
  const last = values[values.length - 1]
  if (!last) return variants

  for (const suffix of KOREAN_PARTICLE_SUFFIXES) {
    if (
      !last.endsWith(suffix) ||
      last.length <= suffix.length
    ) {
      continue
    }

    variants.push({
      values: [
        ...values.slice(0, -1),
        last.slice(0, -suffix.length),
      ],
      suffix,
    })
  }

  return variants
}

function averageTokenEditRatio(
  observed: string[],
  expected: string[],
): number {
  return observed.reduce((sum, value, index) => {
    const target = expected[index]
    return (
      sum +
      distance(value, target) /
        Math.max(value.length, target.length)
    )
  }, 0) / expected.length
}

function buildComponentReplacement(
  text: string,
  contentTokens: HangulToken[],
  canonical: CanonicalComponents,
  suffix: string,
): string {
  let replacement = canonical.values[0]

  for (
    let index = 1;
    index < canonical.values.length;
    index += 1
  ) {
    const observedGap = text.slice(
      contentTokens[index - 1].end,
      contentTokens[index].start,
    )
    const containsFiller = /[가-힣]/.test(observedGap)
    replacement += containsFiller
      ? observedGap
      : canonical.separators[index - 1] || ' '
    replacement += canonical.values[index]
  }

  return replacement + suffix
}

function scoreFuzzyPronunciation(
  observed: string[],
  aliasTokens: string[],
): number | null {
  const exactTokenCount = observed.reduce(
    (count, value, index) =>
      count + (value === aliasTokens[index] ? 1 : 0),
    0,
  )
  if (
    exactTokenCount < Math.ceil(aliasTokens.length / 2)
  ) {
    return null
  }

  const syllableRatio = averageTokenEditRatio(
    observed,
    aliasTokens,
  )
  const observedJamo = observed.join('').normalize('NFD')
  const aliasJamo = aliasTokens.join('').normalize('NFD')
  const jamoDistance = distance(observedJamo, aliasJamo)
  const jamoRatio =
    jamoDistance /
    Math.max(observedJamo.length, aliasJamo.length)
  const combinedScore =
    syllableRatio * 0.55 + jamoRatio * 0.45

  if (
    syllableRatio > MAX_CONTEXTUAL_SYLLABLE_RATIO ||
    jamoRatio > MAX_CONTEXTUAL_JAMO_RATIO ||
    jamoDistance > MAX_CONTEXTUAL_JAMO_DISTANCE ||
    combinedScore > MAX_CONTEXTUAL_COMBINED_SCORE
  ) {
    return null
  }

  return combinedScore
}

/**
 * 동적 별칭과 STT가 조금 다를 때만 문맥 안에서 보수적으로 보정합니다.
 * standalone 필러는 비교에서 건너뛰지만 원래 간격째 다시 넣어 화면에 남깁니다.
 */
function applyFuzzyContextualPronunciations(
  text: string,
  aliases: ContextualPhoneticAlias[],
): string {
  const tokens = extractHangulTokens(text)
  const replacements: FuzzyPronunciationMatch[] = []

  for (
    let startTokenIndex = 0;
    startTokenIndex < tokens.length;
    startTokenIndex += 1
  ) {
    const firstToken = tokens[startTokenIndex]
    if (firstToken.filler) continue

    const matches: FuzzyPronunciationMatch[] = []

    for (const {
      alias,
      canonical,
      canonicalKey,
    } of aliases) {
      const aliasTokens = alias.split(/\s+/).filter(Boolean)
      const canonicalParts =
        splitCanonicalComponents(canonical)

      // 구성요소 경계를 알 수 있을 때만 부분 치환해야 필러 위치를 보존할 수 있습니다.
      if (
        aliasTokens.length < 2 ||
        aliasTokens.length !== canonicalParts.values.length
      ) {
        continue
      }

      const contentTokens: HangulToken[] = []
      let fillerCount = 0
      let endTokenIndex = startTokenIndex - 1

      for (
        let tokenIndex = startTokenIndex;
        tokenIndex < tokens.length;
        tokenIndex += 1
      ) {
        const token = tokens[tokenIndex]
        if (tokenIndex > startTokenIndex) {
          const previous = tokens[tokenIndex - 1]
          const gap = text.slice(previous.end, token.start)
          const allowedGap = previous.filler || token.filler
            ? /^[\s,!?;:-]*$/
            : /^[\s-]*$/
          if (!allowedGap.test(gap)) break
        }

        if (token.filler) {
          fillerCount += 1
          if (
            fillerCount >
            MAX_FILLERS_BETWEEN_TERM_PARTS
          ) {
            break
          }
          continue
        }

        contentTokens.push(token)
        endTokenIndex = tokenIndex
        if (contentTokens.length >= aliasTokens.length) break
      }

      if (contentTokens.length !== aliasTokens.length) {
        continue
      }

      for (const variant of particleVariants(
        contentTokens.map(({ value }) => value),
      )) {
        const score = scoreFuzzyPronunciation(
          variant.values,
          aliasTokens,
        )
        if (score === null) continue

        matches.push({
          canonicalKey,
          start: firstToken.start,
          end:
            contentTokens[contentTokens.length - 1]?.end ??
            firstToken.end,
          endTokenIndex,
          replacement: buildComponentReplacement(
            text,
            contentTokens,
            canonicalParts,
            variant.suffix,
          ),
          score,
        })
      }
    }

    const bestByCanonical = new Map<
      string,
      FuzzyPronunciationMatch
    >()
    for (const match of matches) {
      const previous =
        bestByCanonical.get(match.canonicalKey)
      if (!previous || match.score < previous.score) {
        bestByCanonical.set(match.canonicalKey, match)
      }
    }

    const ranked = [...bestByCanonical.values()].sort(
      (left, right) => left.score - right.score,
    )
    const best = ranked[0]
    if (!best) continue

    const runnerUp = ranked[1]
    if (
      runnerUp &&
      runnerUp.score - best.score <
        MIN_CONTEXTUAL_CANONICAL_MARGIN
    ) {
      continue
    }

    replacements.push(best)
    startTokenIndex = best.endTokenIndex
  }

  let corrected = text
  for (
    let index = replacements.length - 1;
    index >= 0;
    index -= 1
  ) {
    const replacement = replacements[index]
    corrected =
      corrected.slice(0, replacement.start) +
      replacement.replacement +
      corrected.slice(replacement.end)
  }
  return corrected
}

function correctContextualPronunciations(
  text: string,
  entries: SpeechTermAlias[],
): string {
  const aliases = buildContextualPhoneticAliases(entries)
  const exactlyCorrected =
    applyExactContextualPronunciations(text, aliases)
  return applyFuzzyContextualPronunciations(
    exactlyCorrected,
    aliases,
  )
}

function correctWord(word: string, dict: string[]): string {
  if (word.length < MIN_WORD_LEN) return word

  const normalizedWord = normalizeTerm(word)
  const candidates = dict
    .filter((candidate) => !/\s/.test(candidate))
    .map((candidate) => ({
      candidate,
      normalized: normalizeTerm(candidate),
    }))
    .filter(
      ({ normalized }) =>
        normalized.length >= MIN_WORD_LEN &&
        scriptKind(normalized) === scriptKind(normalizedWord),
    )
    .map(({ candidate, normalized }) => ({
      candidate,
      normalized,
      editDistance: distance(normalizedWord, normalized),
    }))
    .sort((left, right) => left.editDistance - right.editDistance)

  const best = candidates[0]
  if (!best) return word
  if (best.editDistance === 0) return best.candidate

  const second = candidates[1]
  const ratio =
    best.editDistance /
    Math.max(normalizedWord.length, best.normalized.length)
  if (
    ratio > MAX_EDIT_RATIO ||
    (second && second.editDistance === best.editDistance)
  ) {
    return word
  }

  return best.candidate
}

/**
 * Pass STT output through the presentation's own vocabulary and swap in
 * near-matches word-by-word (어절 단위). Conservative by design: a word only
 * gets corrected if it's a close edit-distance match to a term the student's
 * own script/slides already use.
 */
export function correctText(
  text: string,
  dict: string[],
  speechTermAliases: SpeechTermAlias[] = [],
): string {
  if (!dict.length && !speechTermAliases.length) return text
  return correctContextualPronunciations(
    text,
    speechTermAliases,
  )
    .split(/(\s+)/)
    .map((chunk) => {
      if (/^\s*$/.test(chunk)) return chunk
      const trailing = chunk.match(/[.,!?;:)\]]*$/)?.[0] ?? ''
      const core = trailing ? chunk.slice(0, chunk.length - trailing.length) : chunk
      if (!core) return chunk
      if (FILLER_TOKEN_PATTERN.test(core)) return chunk
      return correctWord(core, dict) + trailing
    })
    .join('')
}
