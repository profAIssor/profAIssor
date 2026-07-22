import type { Slide } from '../types'

// Speaking-rate assumption shared with ReportScreen's estimate (~120 어절/분).
const WORDS_PER_MINUTE = 120
// Rough fallback when there's no script to count — a slide-only deck is
// estimated at ~1 minute of narration per slide.
const MINUTES_PER_SLIDE = 1

/** Count whitespace-separated words (어절) in a script. */
export function countWords(text: string): number {
  const trimmed = text.trim()
  return trimmed ? trimmed.split(/\s+/).length : 0
}

/**
 * Estimate presentation length in minutes.
 *
 * A real script drives the estimate through speaking rate; when only slides
 * are provided, fall back to a per-slide estimate. Returns 0 when there's
 * nothing to estimate from.
 */
export function estimatePresentationMinutes(script: string, slides: Slide[]): number {
  const words = countWords(script)
  if (words > 0) return words / WORDS_PER_MINUTE

  const filledSlides = slides.filter((slide) => slide.text.trim().length > 0).length
  return filledSlides * MINUTES_PER_SLIDE
}

/** Human-friendly label like "약 2분 30초" / "약 45초". */
export function formatMinutes(minutes: number): string {
  if (minutes <= 0) return '—'
  const totalSeconds = Math.round(minutes * 60)
  const mm = Math.floor(totalSeconds / 60)
  const ss = totalSeconds % 60
  if (mm === 0) return `약 ${ss}초`
  if (ss === 0) return `약 ${mm}분`
  return `약 ${mm}분 ${ss}초`
}
