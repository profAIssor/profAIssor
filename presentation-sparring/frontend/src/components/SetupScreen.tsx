import { useState } from 'react'
import { PERSONAS } from '../personas'
import type { PersonaId, Slide } from '../types'
import SlideInput from './SlideInput'

interface Props {
  onStart: (data: { script: string; slides: Slide[]; personaIds: PersonaId[] }) => void
}

const SAMPLE_SCRIPT =
  '안녕하세요. 저희 연구는 트랜스포머 모델의 어텐션 계산 효율성을 개선하는 방법을 제안합니다. ' +
  '기존 어텐션은 계산 복잡도가 높다는 문제가 있었고, 저희는 이를 줄이는 방향으로 접근했습니다. ' +
  '음 그 결과 속도가 빨라졌습니다. 감사합니다.'

const SAMPLE_SLIDES: Slide[] = [
  { index: 1, text: '문제 정의: 셀프 어텐션의 계산 복잡도 O(n^2)' },
  { index: 2, text: '제안 방법: 희소 어텐션(sparse attention)으로 O(n log n) 달성' },
  { index: 3, text: '실험 결과: GLUE 벤치마크에서 2.3배 속도 향상, 정확도 유지' },
]

export default function SetupScreen({ onStart }: Props) {
  const [script, setScript] = useState(SAMPLE_SCRIPT)
  const [slides, setSlides] = useState<Slide[]>(SAMPLE_SLIDES)
  const [selected, setSelected] = useState<PersonaId[]>(['professor', 'peer'])

  const toggle = (id: PersonaId) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id],
    )
  }

  const canStart = script.trim().length > 0 && selected.length > 0

  return (
    <div className="mx-auto max-w-3xl space-y-8 px-4 py-10">
      <header>
        <h1 className="text-3xl font-bold tracking-tight">🎤 발표 스파링 파트너</h1>
        <p className="mt-2 text-slate-400">
          여러 관점의 까다로운 청중을 동시에 상대하는 발표 질의응답 스파링 도구.
        </p>
      </header>

      <section className="space-y-2">
        <label className="block text-sm font-semibold text-slate-200">발표 대본</label>
        <textarea
          value={script}
          onChange={(e) => setScript(e.target.value)}
          rows={7}
          placeholder="실제로 발표할 대본을 그대로 붙여넣으세요."
          className="w-full resize-y rounded-xl border border-slate-700 bg-slate-800/60 px-4 py-3 text-sm leading-relaxed outline-none focus:border-indigo-500"
        />
      </section>

      <section className="space-y-3">
        <label className="block text-sm font-semibold text-slate-200">
          발표자료 슬라이드 텍스트
        </label>
        <p className="text-xs text-slate-500">
          슬라이드별 핵심 텍스트를 입력하면, 대본에서 말로 전달되지 않은 슬라이드 내용을 리포트에서 찾아줍니다.
        </p>
        <SlideInput slides={slides} onChange={setSlides} />
      </section>

      <section className="space-y-3">
        <label className="block text-sm font-semibold text-slate-200">
          청중 페르소나 선택 <span className="text-slate-500">(1개 이상)</span>
        </label>
        <div className="grid gap-3 sm:grid-cols-3">
          {PERSONAS.map((p) => {
            const active = selected.includes(p.id)
            return (
              <button
                key={p.id}
                type="button"
                onClick={() => toggle(p.id)}
                className={
                  'rounded-xl border p-4 text-left transition ' +
                  (active
                    ? 'border-indigo-500 bg-indigo-500/10 ring-1 ring-indigo-500'
                    : 'border-slate-700 bg-slate-800/40 hover:border-slate-500')
                }
              >
                <div className="text-2xl">{p.emoji}</div>
                <div className="mt-1 font-semibold">{p.name}</div>
                <div className="mt-1 text-xs leading-snug text-slate-400">{p.blurb}</div>
              </button>
            )
          })}
        </div>
      </section>

      <button
        type="button"
        disabled={!canStart}
        onClick={() => onStart({ script, slides: slides.filter((s) => s.text.trim()), personaIds: selected })}
        className="w-full rounded-xl bg-indigo-600 py-3 text-lg font-semibold transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
      >
        스파링 시작 →
      </button>
    </div>
  )
}
