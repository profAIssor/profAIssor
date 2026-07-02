import type { Slide } from '../types'

interface Props {
  slides: Slide[]
  onChange: (slides: Slide[]) => void
}

/** Dynamic list of slide-text inputs (add / remove / edit). */
export default function SlideInput({ slides, onChange }: Props) {
  const update = (i: number, text: string) => {
    const next = slides.map((s, idx) => (idx === i ? { ...s, text } : s))
    onChange(next)
  }

  const add = () => {
    onChange([...slides, { index: slides.length + 1, text: '' }])
  }

  const remove = (i: number) => {
    const next = slides
      .filter((_, idx) => idx !== i)
      .map((s, idx) => ({ ...s, index: idx + 1 }))
    onChange(next)
  }

  return (
    <div className="space-y-3">
      {slides.map((slide, i) => (
        <div key={i} className="flex gap-2">
          <span className="mt-2 w-16 shrink-0 text-sm font-semibold text-indigo-300">
            슬라이드 {slide.index}
          </span>
          <textarea
            value={slide.text}
            onChange={(e) => update(i, e.target.value)}
            placeholder="이 슬라이드의 핵심 텍스트 (제목/불릿 요점)"
            rows={2}
            className="flex-1 resize-y rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2 text-sm outline-none focus:border-indigo-500"
          />
          <button
            type="button"
            onClick={() => remove(i)}
            className="mt-1 h-8 w-8 shrink-0 rounded-lg border border-slate-700 text-slate-400 hover:border-rose-500 hover:text-rose-400"
            aria-label="슬라이드 삭제"
          >
            ✕
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={add}
        className="rounded-lg border border-dashed border-slate-600 px-4 py-2 text-sm text-slate-300 hover:border-indigo-500 hover:text-indigo-300"
      >
        + 슬라이드 추가
      </button>
    </div>
  )
}
