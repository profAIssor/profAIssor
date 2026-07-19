import { FileText, Settings2, Sparkles, Users } from 'lucide-react'
import { useState } from 'react'
import { PERSONAS } from '../personas'
import type { AcademicField, Difficulty, PersonaId, Slide } from '../types'
import SlideInput from './SlideInput'

interface Props {
  onStart: (data: {
    script: string
    slides: Slide[]
    personaIds: PersonaId[]
    difficulty: Difficulty
    maxTurns: number
    field: AcademicField | null
  }) => void
}

const DIFFICULTY_OPTIONS: { id: Difficulty; label: string }[] = [
  { id: 'easy', label: '쉬움' },
  { id: 'medium', label: '보통' },
  { id: 'hard', label: '어려움' },
]

const FIELD_OPTIONS: { id: AcademicField; label: string }[] = [
  { id: 'engineering', label: '공학' },
  { id: 'humanities', label: '인문사회' },
  { id: 'natural', label: '자연과학' },
]

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
  const [script, setScript] = useState('')
  const [slides, setSlides] = useState<Slide[]>([])

  // 중립적인 기본 평가자 초기 선택
  const [selected, setSelected] = useState<PersonaId[]>(['standard'])
  const [difficulty, setDifficulty] = useState<Difficulty>('medium')
  const [maxTurns, setMaxTurns] = useState(2)
  const [field, setField] = useState<AcademicField | null>(null)

  const toggle = (id: PersonaId) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id],
    )
  }

  const hasContent =
    script.trim().length > 0 || slides.some((s) => s.text.trim().length > 0)

  const fillSample = () => {
    if (
      hasContent &&
      !window.confirm('입력한 대본/슬라이드가 예시 데이터로 대체됩니다. 계속할까요?')
    ) {
      return
    }

    setScript(SAMPLE_SCRIPT)
    setSlides(SAMPLE_SLIDES)
  }

  // 대본 또는 슬라이드 단독 입력 지원
  const canStart = hasContent && selected.length > 0

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <div className="space-y-2 text-center">
        <h1 className="text-4xl font-extrabold tracking-tight text-slate-900 sm:text-5xl">
          prof<span className="text-indigo-600">AI</span>ssor
        </h1>
        <p className="mx-auto max-w-2xl text-lg text-slate-500">
          여러 관점의 까다로운 청중을 동시에 상대하는 발표 질의응답 스파링 도구.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-12">
        {/* 좌측 영역: 대본 및 슬라이드 */}
        <div className="space-y-6 lg:col-span-7">
          <div className="space-y-4 rounded-2xl border border-slate-200/80 bg-white p-6 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <label
                htmlFor="script-textarea"
                className="flex items-center gap-2 text-lg font-semibold text-slate-800"
              >
                <FileText className="h-5 w-5 text-indigo-500" />
                발표 대본
              </label>
              <button
                type="button"
                onClick={fillSample}
                className="shrink-0 text-xs font-semibold text-indigo-500 hover:text-indigo-700 hover:underline"
              >
                예시 데이터로 채우기
              </button>
            </div>
            <p className="text-xs text-slate-400">
              실제로 발표할 대본을 그대로 붙여넣으세요. AI 심사관이 이를 바탕으로
              날카로운 꼬리 질문을 던집니다.
            </p>
            <textarea
              id="script-textarea"
              value={script}
              onChange={(e) => setScript(e.target.value)}
              rows={9}
              placeholder="실제로 발표할 대본을 그대로 붙여넣으세요."
              className="w-full resize-y rounded-xl border border-slate-200 bg-slate-50/50 px-4 py-3 text-sm leading-relaxed text-slate-700 outline-none focus:border-indigo-500 focus:bg-white focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div className="space-y-3 rounded-2xl border border-slate-200/80 bg-white p-6 shadow-sm">
            <label className="flex items-center gap-2 text-lg font-semibold text-slate-800">
              <Sparkles className="h-5 w-5 text-indigo-500" />
              발표자료 슬라이드 텍스트
            </label>
            {/* 슬라이드 분석 목적 안내 재추가 */}
            <p className="text-xs text-slate-400">
              발표에서 빠진 슬라이드 내용을 함께 분석합니다.
            </p>
            <SlideInput slides={slides} onChange={setSlides} />
          </div>
        </div>

        {/* 우측 영역: 페르소나 선택 및 시작 버튼 */}
        <div className="space-y-6 lg:col-span-5">
          <div className="space-y-5 rounded-2xl border border-slate-200/80 bg-white p-6 shadow-sm">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-800">
              <Users className="h-5 w-5 text-indigo-500" />
              청중 페르소나 선택
              <span className="text-xs font-normal text-slate-400">(1개 이상)</span>
            </h2>

            <div className="space-y-3">
              {PERSONAS.map((p) => {
                const active = selected.includes(p.id)

                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => toggle(p.id)}
                    className={
                      'relative flex w-full items-start gap-3.5 rounded-xl border-2 p-4 text-left transition-all ' +
                      (active
                        ? 'border-indigo-600 bg-indigo-50/40 shadow-sm'
                        : 'border-slate-100 hover:border-slate-200 hover:bg-slate-50/50')
                    }
                  >
                    <span className="select-none text-3xl" role="img" aria-label={p.name}>
                      {p.emoji}
                    </span>
                    <div className="space-y-1 pr-6">
                      <div className="text-sm font-bold text-slate-800">{p.name}</div>
                      <p className="text-xs leading-normal text-slate-500">{p.blurb}</p>
                    </div>
                    {active && (
                      <div className="absolute right-3.5 top-3.5 flex h-4 w-4 items-center justify-center rounded-full bg-indigo-600">
                        <div className="h-1.5 w-1.5 rounded-full bg-white" />
                      </div>
                    )}
                  </button>
                )
              })}
            </div>
          </div>

          <div className="space-y-5 rounded-2xl border border-slate-200/80 bg-white p-6 shadow-sm">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-800">
              <Settings2 className="h-5 w-5 text-indigo-500" />
              세부 설정
            </h2>

            <div className="space-y-2">
              <span className="text-xs font-semibold text-slate-500">질문 난이도</span>
              <div className="flex gap-2">
                {DIFFICULTY_OPTIONS.map((opt) => (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => setDifficulty(opt.id)}
                    className={
                      'flex-1 rounded-lg border-2 py-2 text-sm font-semibold transition-all ' +
                      (difficulty === opt.id
                        ? 'border-indigo-600 bg-indigo-50/40 text-indigo-700'
                        : 'border-slate-100 text-slate-500 hover:border-slate-200')
                    }
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <span className="text-xs font-semibold text-slate-500">
                최대 꼬리질문 횟수
              </span>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => setMaxTurns((current) => Math.max(0, current - 1))}
                  disabled={maxTurns <= 0}
                  className="h-8 w-8 rounded-lg border border-slate-200 text-slate-500 hover:border-indigo-400 hover:text-indigo-600 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  −
                </button>
                <span className="w-6 text-center text-sm font-bold text-slate-800">
                  {maxTurns}
                </span>
                <button
                  type="button"
                  onClick={() => setMaxTurns((current) => Math.min(3, current + 1))}
                  disabled={maxTurns >= 3}
                  className="h-8 w-8 rounded-lg border border-slate-200 text-slate-500 hover:border-indigo-400 hover:text-indigo-600 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  +
                </button>
              </div>
              {/* 꼬리질문 구성 안내 재추가 */}
              <p className="text-xs leading-relaxed text-slate-400">
                총 질문을 {maxTurns + 1}회 진행합니다.
              </p>
            </div>

            <div className="space-y-2">
              <span className="text-xs font-semibold text-slate-500">전공 계열 (선택)</span>
              <div className="flex flex-wrap gap-2">
                {FIELD_OPTIONS.map((opt) => (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => setField((prev) => (prev === opt.id ? null : opt.id))}
                    className={
                      'rounded-lg border-2 px-3 py-1.5 text-xs font-semibold transition-all ' +
                      (field === opt.id
                        ? 'border-indigo-600 bg-indigo-50/40 text-indigo-700'
                        : 'border-slate-100 text-slate-500 hover:border-slate-200')
                    }
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <button
            type="button"
            disabled={!canStart}
            onClick={() =>
              onStart({
                script,
                slides: slides.filter((s) => s.text.trim()),
                personaIds: selected,
                difficulty,
                maxTurns,
                field,
              })
            }
            className="w-full rounded-xl bg-indigo-600 py-4 text-lg font-semibold text-white shadow-lg shadow-indigo-600/10 transition-all hover:scale-[1.01] hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:scale-100"
          >
            스파링 시작 →
          </button>

          {!canStart && (
            <p className="text-center text-xs text-slate-400">
              {!hasContent
                ? '발표 대본 또는 슬라이드 중 하나는 입력해야 시작할 수 있어요'
                : '청중 페르소나를 1개 이상 선택해주세요'}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}