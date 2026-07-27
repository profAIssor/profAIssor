import { distance } from 'fastest-levenshtein'

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
const MAX_PHONETIC_VARIANTS_PER_TERM = 32

/**
 * 영문을 임의로 번역하는 표가 아니라 STT가 자주 만드는 발음 표기 후보입니다.
 * 실제 현재 질문/관련 슬라이드에 canonical 영문 구절이 있을 때만 활성화됩니다.
 */
const PHONETIC_COMPONENT_ALIASES: Record<
  string,
  readonly string[]
> = {
  attention: ['어텐션', '어탠션', '어텐전'],
  cross: ['크로스'],
  dot: ['닷'],
  full: ['풀'],
  global: ['글로벌'],
  head: ['헤드'],
  local: ['로컬'],
  masked: ['마스크드'],
  multi: ['멀티'],
  product: ['프로덕트'],
  scaled: ['스케일드'],
  self: ['셀프'],
  sliding: ['슬라이딩'],
  sparse: ['스파스', '스파즈', '스파이스'],
  window: ['윈도우', '윈도'],
}

const KOREAN_PARTICLE_LOOKAHEAD =
  '(?:은|는|이|가|을|를|과|와|의|으로|로|에서|에게|만|도|처럼|보다|' +
  '입니다|입니까|인가|인|이고|이며|이라고|라는|라면|예요|이에요|였다|였습니다)'

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

interface ContextualPhoneticAlias {
  alias: string
  canonical: string
  canonicalKey: string
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function buildVariantComponents(
  components: string[],
): string[][] {
  let variants: string[][] = [[]]

  for (const component of components) {
    const pronunciations =
      PHONETIC_COMPONENT_ALIASES[component]
    if (!pronunciations) return []

    const options = [component, ...pronunciations]
    const nextVariants: string[][] = []
    for (const variant of variants) {
      for (const option of options) {
        nextVariants.push([...variant, option])
        if (
          nextVariants.length >=
          MAX_PHONETIC_VARIANTS_PER_TERM
        ) {
          break
        }
      }
      if (
        nextVariants.length >=
        MAX_PHONETIC_VARIANTS_PER_TERM
      ) {
        break
      }
    }
    variants = nextVariants
  }

  return variants.filter((variant) =>
    variant.some((component) => /[가-힣]/.test(component)),
  )
}

/**
 * 현재 문맥에 실제로 존재하는 2단어 이상의 영문 전문 용어만
 * 한국어 음역 후보와 연결합니다. 충돌하는 음역은 모두 폐기합니다.
 */
function buildContextualPhoneticAliases(
  canonicals: string[],
): ContextualPhoneticAlias[] {
  const aliases = new Map<
    string,
    ContextualPhoneticAlias | null
  >()

  for (const canonical of canonicals) {
    const trimmed = canonical.trim()
    if (
      !/^[A-Za-z][A-Za-z0-9]*(?:[\s-]+[A-Za-z][A-Za-z0-9]*)+$/.test(
        trimmed,
      )
    ) {
      continue
    }

    const components =
      trimmed.match(/[A-Za-z][A-Za-z0-9]*/g)
        ?.map((component) => component.toLowerCase()) ?? []
    if (
      components.length < 2 ||
      components.some(
        (component) =>
          !PHONETIC_COMPONENT_ALIASES[component],
      )
    ) {
      continue
    }

    const canonicalKey = components.join(' ')
    for (const variant of buildVariantComponents(components)) {
      const alias = variant.join(' ')
      const aliasKey = normalizeTerm(alias)
        .replace(/-/g, ' ')
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
        canonical: trimmed,
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

function correctContextualPronunciations(
  text: string,
  canonicals: string[],
): string {
  let corrected = text

  for (const { alias, canonical } of
    buildContextualPhoneticAliases(canonicals)) {
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
export function correctText(text: string, dict: string[]): string {
  if (!dict.length) return text
  return correctContextualPronunciations(text, dict)
    .split(/(\s+)/)
    .map((chunk) => {
      if (/^\s*$/.test(chunk)) return chunk
      const trailing = chunk.match(/[.,!?;:)\]]*$/)?.[0] ?? ''
      const core = trailing ? chunk.slice(0, chunk.length - trailing.length) : chunk
      if (!core) return chunk
      if (/^(?:어+|음+|으+음+)$/.test(core)) return chunk
      return correctWord(core, dict) + trailing
    })
    .join('')
}
