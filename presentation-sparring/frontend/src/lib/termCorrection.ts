import { closest, distance } from 'fastest-levenshtein'

// Common Korean connectors/particles that show up in every script — never
// worth treating as a "term" to correct toward.
const STOPWORDS = new Set([
  '그리고', '그러나', '하지만', '또한', '때문', '위해', '대한', '통해', '있는', '있다',
  '합니다', '입니다', '이다', '및', '등',
])

// 2-char words are excluded: at that length any single-edit correction already
// exceeds MAX_EDIT_RATIO, but a 2-char word can still spuriously match a
// slightly longer dict term that has a particle attached (e.g. "오늘" vs
// "오늘은") because the ratio denominator uses the longer of the two lengths.
const MIN_WORD_LEN = 3
// How much of a word's length may differ (edit distance) and still count as
// "the same word, mis-transcribed". Kept low so we only fix plausible STT
// mishearings, never swap in an unrelated dictionary term.
const MAX_EDIT_RATIO = 0.34

/**
 * Candidate terms an STT engine is likely to mis-hear: everything in the
 * script + slide text except common particles/connectors.
 */
export function buildTermDictionary(script: string, slides: { text: string }[]): string[] {
  const source = script + '\n' + slides.map((s) => s.text).join('\n')
  const tokens = source.match(/[A-Za-z0-9가-힣]{2,}/g) ?? []
  const dict = new Set<string>()
  for (const t of tokens) {
    if (STOPWORDS.has(t)) continue
    dict.add(t)
  }
  return [...dict]
}

function correctWord(word: string, dict: string[]): string {
  if (word.length < MIN_WORD_LEN || dict.includes(word)) return word
  const match = closest(word, dict)
  const d = distance(word, match)
  if (d === 0 || d / Math.max(word.length, match.length) > MAX_EDIT_RATIO) return word
  return match
}

/**
 * Pass STT output through the presentation's own vocabulary and swap in
 * near-matches word-by-word (어절 단위). Conservative by design: a word only
 * gets corrected if it's a close edit-distance match to a term the student's
 * own script/slides already use.
 */
export function correctText(text: string, dict: string[]): string {
  if (!dict.length) return text
  return text
    .split(/(\s+)/)
    .map((chunk) => {
      if (/^\s*$/.test(chunk)) return chunk
      const trailing = chunk.match(/[.,!?;:)\]]*$/)?.[0] ?? ''
      const core = trailing ? chunk.slice(0, chunk.length - trailing.length) : chunk
      if (!core) return chunk
      return correctWord(core, dict) + trailing
    })
    .join('')
}
