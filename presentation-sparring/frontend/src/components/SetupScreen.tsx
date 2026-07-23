import {
  Clock,
  FileText,
  Settings2,
  Sparkles,
  Users,
} from 'lucide-react'
import {
  useCallback,
  useEffect,
  useState,
} from 'react'
import type { ChangeEvent } from 'react'
import { fetchPersonas } from '../api'
import {
  estimatePresentationMinutes,
  formatMinutes,
} from '../lib/timing'
import {
  getCachedPersonas,
  replacePersonaCache,
} from '../personas'
import type {
  AcademicField,
  Difficulty,
  Persona,
  PersonaId,
  Slide,
} from '../types'
import SlideInput from './SlideInput'

interface SetupData {
  script: string
  slides: Slide[]
  personaIds: PersonaId[]
  difficulty: Difficulty
  maxTurns: number
  field: AcademicField | null
}

interface Props {
  onStart: (data: SetupData) => void
  onSkipToReport: (data: SetupData) => void
}

const DIFFICULTY_OPTIONS: {
  id: Difficulty
  label: string
}[] = [
  { id: 'easy', label: '쉬움' },
  { id: 'medium', label: '보통' },
  { id: 'hard', label: '어려움' },
]

const FIELD_OPTIONS: {
  id: AcademicField
  label: string
}[] = [
  { id: 'engineering', label: '공학' },
  { id: 'humanities', label: '인문사회' },
  { id: 'natural', label: '자연과학' },
]

const SAMPLE_SCRIPT =
  '안녕하세요. 저희 연구는 트랜스포머 모델의 어텐션 계산 효율성을 개선하는 방법을 제안합니다. ' +
  '기존 Self-Attention은 입력 길이가 늘수록 계산량이 크게 증가합니다. ' +
  '저희는 Sparse Attention을 적용해 일부 토큰 관계만 계산하도록 구성했습니다. ' +
  '실험 결과 처리 속도는 2.3배 향상되었고 정확도는 기존 수준을 유지했습니다. 감사합니다.'

const SAMPLE_SLIDES: Slide[] = [
  {
    index: 1,
    text: '문제 정의\nSelf-Attention의 계산 복잡도 O(n²)',
  },
  {
    index: 2,
    text: '제안 방법\nSparse Attention으로 비교 대상 축소\n계산 복잡도 O(n log n)',
  },
  {
    index: 3,
    text: '실험 결과\n처리 속도 2.3배 향상\n정확도 유지',
  },
]

/** 발표 자료 등록과 질의응답 조건 설정 화면. */
export default function SetupScreen({
  onStart,
  onSkipToReport,
}: Props) {
  const cachedPersonas = getCachedPersonas()

  const [script, setScript] = useState('')
  const [slides, setSlides] = useState<Slide[]>([])
  const [personas, setPersonas] =
    useState<Persona[]>(cachedPersonas)
  const [selected, setSelected] =
    useState<PersonaId[]>(['standard'])
  const [personaLoading, setPersonaLoading] =
    useState(cachedPersonas.length === 0)
  const [personaError, setPersonaError] =
    useState<string | null>(null)
  const [difficulty, setDifficulty] =
    useState<Difficulty>('medium')
  const [maxTurns, setMaxTurns] = useState(2)
  const [field, setField] =
    useState<AcademicField | null>(null)

  /** 백엔드 공개 페르소나 목록 동기화. */
  const loadPersonas = useCallback(async () => {
    setPersonaLoading(true)
    setPersonaError(null)

    try {
      const response = await fetchPersonas()
      const nextPersonas = replacePersonaCache(response)
      const availableIds = new Set(
        nextPersonas.map((persona) => persona.id),
      )

      setPersonas(nextPersonas)
      setSelected((current) => {
        const retained = current.filter((id) =>
          availableIds.has(id),
        )
        if (retained.length > 0) return retained

        const defaultPersona =
          nextPersonas.find(
            (persona) => persona.id === 'standard',
          ) ?? nextPersonas[0]
        return [defaultPersona.id]
      })
    } catch (caught) {
      setPersonaError(
        caught instanceof Error
          ? caught.message
          : '평가자 목록을 불러오지 못했습니다.',
      )
    } finally {
      setPersonaLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadPersonas()
  }, [loadPersonas])

  const toggle = (id: PersonaId) => {
    setSelected((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : [...current, id],
    )
  }

  const hasContent =
    script.trim().length > 0 ||
    slides.some(
      (slide) => slide.text.trim().length > 0,
    )
  const canStart =
    hasContent &&
    selected.length > 0 &&
    personas.length > 0
  const totalQuestionCount = maxTurns + 1

  // 대본 어절 수 또는 슬라이드 수 기반 발표 예상 시간 계산
  const estimatedMinutes =
    estimatePresentationMinutes(script, slides)
  const estimateBasis =
    script.trim().length > 0
      ? '대본 약 120어절/분 기준'
      : '슬라이드 수 기준 추정'

  /** 현재 설정값의 공통 요청 데이터 생성. */
  const buildData = (): SetupData => ({
    script: script.trim(),
    slides: slides.filter(
      (slide) => slide.text.trim(),
    ),
    personaIds: selected,
    difficulty,
    maxTurns,
    field,
  })

  const fillSample = () => {
    if (
      hasContent &&
      !window.confirm(
        '입력한 대본과 슬라이드가 예시 데이터로 대체됩니다. 계속할까요?',
      )
    ) {
      return
    }
    setScript(SAMPLE_SCRIPT)
    setSlides(SAMPLE_SLIDES)
  }

  const startSparring = () => {
    if (!canStart) return
    onStart(buildData())
  }

  return (
    <div className="mx-auto max-w-7xl">
      <div className="mb-8 text-center">
        <h1 className="text-3xl font-black tracking-tight text-slate-900">
          prof
          <span className="text-indigo-600">
            AI
          </span>
          ssor
        </h1>
        <p className="mt-2 text-sm text-slate-500">
          발표 자료를 바탕으로 예상 질문과 답변 대응을 연습하는 질의응답 스파링 도구
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-12">
        <div className="space-y-6 lg:col-span-7">
          <section className="space-y-3 rounded-2xl border border-slate-200/80 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <label className="flex items-center gap-2 text-lg font-semibold text-slate-800">
                <FileText className="h-5 w-5 text-indigo-500" />
                발표 대본
              </label>
              <button
                type="button"
                onClick={fillSample}
                className="text-xs font-semibold text-indigo-600 hover:text-indigo-700"
              >
                예시 데이터로 채우기
              </button>
            </div>
            <p className="text-xs leading-relaxed text-slate-400">
              실제 발표 대본을 입력하면 시스템이 슬라이드 순서를 고려해 관련 구간을 내부적으로 추정합니다.
              추정 결과는 별도 계획 화면에 표시하지 않고 질문 생성과 답변 평가의 근거로만 사용합니다.
            </p>
            <textarea
              value={script}
              onChange={(
                event: ChangeEvent<HTMLTextAreaElement>,
              ) => setScript(event.target.value)}
              rows={10}
              placeholder="실제로 발표할 대본을 그대로 붙여넣으세요."
              className="w-full resize-y rounded-xl border border-slate-200 bg-slate-50/50 px-4 py-3 text-sm leading-relaxed text-slate-700 outline-none focus:border-indigo-500 focus:bg-white focus:ring-2 focus:ring-indigo-500"
            />
          </section>

          <section className="space-y-3 rounded-2xl border border-slate-200/80 bg-white p-6 shadow-sm">
            <label className="flex items-center gap-2 text-lg font-semibold text-slate-800">
              <Sparkles className="h-5 w-5 text-indigo-500" />
              발표자료 슬라이드 텍스트
            </label>
            <p className="text-xs leading-relaxed text-slate-400">
              PPTX 또는 PDF를 최대 60장까지 업로드할 수 있습니다. PDF의 시각적 줄바꿈은
              서버에서 문장 흐름에 맞게 정리한 뒤 표시합니다. 추출 결과가 어색한 부분은 직접
              수정할 수 있습니다.
            </p>
            <SlideInput
              slides={slides}
              onChange={setSlides}
            />
          </section>
        </div>

        <aside className="space-y-6 lg:col-span-5">
          <section className="space-y-5 rounded-2xl border border-slate-200/80 bg-white p-6 shadow-sm">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-800">
              <Users className="h-5 w-5 text-indigo-500" />
              청중 페르소나 선택
              <span className="text-xs font-normal text-slate-400">
                1개 이상
              </span>
            </h2>

            {personaLoading &&
              personas.length === 0 && (
                <div className="rounded-xl border border-slate-100 bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
                  평가자 목록을 불러오는 중입니다.
                </div>
              )}

            {!personaLoading &&
              personas.length === 0 && (
                <div className="space-y-3 rounded-xl border border-rose-100 bg-rose-50/50 px-4 py-4">
                  <p className="text-sm leading-relaxed text-rose-700">
                    {personaError ??
                      '평가자 목록을 불러오지 못했습니다.'}
                  </p>
                  <button
                    type="button"
                    onClick={() => void loadPersonas()}
                    className="text-xs font-bold text-indigo-600 hover:text-indigo-700"
                  >
                    다시 불러오기
                  </button>
                </div>
              )}

            {personas.length > 0 && (
              <div className="space-y-3">
                {personas.map((persona) => {
                  const active = selected.includes(
                    persona.id,
                  )
                  return (
                    <button
                      key={persona.id}
                      type="button"
                      onClick={() =>
                        toggle(persona.id)
                      }
                      className={
                        'relative flex w-full items-start gap-3.5 rounded-xl border-2 p-4 text-left transition-all ' +
                        (active
                          ? 'border-indigo-600 bg-indigo-50/40 shadow-sm'
                          : 'border-slate-100 hover:border-slate-200 hover:bg-slate-50/50')
                      }
                    >
                      <span
                        className="select-none text-3xl"
                        role="img"
                        aria-label={persona.name}
                      >
                        {persona.emoji}
                      </span>
                      <div className="space-y-1 pr-6">
                        <div className="text-sm font-bold text-slate-800">
                          {persona.name}
                        </div>
                        <p className="text-xs leading-normal text-slate-500">
                          {persona.blurb}
                        </p>
                      </div>
                      {active && (
                        <span className="absolute right-3.5 top-3.5 h-4 w-4 rounded-full border-[5px] border-indigo-600 bg-white" />
                      )}
                    </button>
                  )
                })}
              </div>
            )}

            {personaError &&
              personas.length > 0 && (
                <div className="flex items-center justify-between gap-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
                  <span>
                    저장된 평가자 목록을 표시하고 있습니다.
                  </span>
                  <button
                    type="button"
                    onClick={() => void loadPersonas()}
                    className="shrink-0 font-bold text-indigo-600"
                  >
                    새로고침
                  </button>
                </div>
              )}
          </section>

          <section className="space-y-5 rounded-2xl border border-slate-200/80 bg-white p-6 shadow-sm">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-800">
              <Settings2 className="h-5 w-5 text-indigo-500" />
              세부 설정
            </h2>

            <div className="space-y-2">
              <span className="text-xs font-semibold text-slate-500">
                질문 난이도
              </span>
              <div className="flex gap-2">
                {DIFFICULTY_OPTIONS.map(
                  (option) => (
                    <button
                      key={option.id}
                      type="button"
                      onClick={() =>
                        setDifficulty(option.id)
                      }
                      className={
                        'flex-1 rounded-lg border-2 py-2 text-sm font-semibold transition-all ' +
                        (difficulty === option.id
                          ? 'border-indigo-600 bg-indigo-50/40 text-indigo-700'
                          : 'border-slate-100 text-slate-500 hover:border-slate-200')
                      }
                    >
                      {option.label}
                    </button>
                  ),
                )}
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-semibold text-slate-500">
                  추가 질문 횟수
                </span>
                <span className="text-[11px] text-slate-400">
                  0~3회
                </span>
              </div>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() =>
                    setMaxTurns((current) =>
                      Math.max(0, current - 1),
                    )
                  }
                  disabled={maxTurns <= 0}
                  className="h-8 w-8 rounded-lg border border-slate-200 text-slate-500 disabled:opacity-40"
                >
                  −
                </button>
                <span className="w-10 text-center text-sm font-bold text-slate-800">
                  {maxTurns}회
                </span>
                <button
                  type="button"
                  onClick={() =>
                    setMaxTurns((current) =>
                      Math.min(3, current + 1),
                    )
                  }
                  disabled={maxTurns >= 3}
                  className="h-8 w-8 rounded-lg border border-slate-200 text-slate-500 disabled:opacity-40"
                >
                  +
                </button>
              </div>
              <p className="text-xs text-slate-400">
                각 평가자마다 기본 질문을 포함해 최대{' '}
                {totalQuestionCount}회 진행합니다. 답변
                불가 뒤 한 번 제공되는 쉬운 재질문은
                질문 수에서 제외합니다.
              </p>
            </div>

            <div className="space-y-2">
              <span className="text-xs font-semibold text-slate-500">
                전공 계열
              </span>
              <div className="flex flex-wrap gap-2">
                {FIELD_OPTIONS.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() =>
                      setField((current) =>
                        current === option.id
                          ? null
                          : option.id,
                      )
                    }
                    className={
                      'rounded-lg border-2 px-3 py-1.5 text-xs font-semibold ' +
                      (field === option.id
                        ? 'border-indigo-600 bg-indigo-50/40 text-indigo-700'
                        : 'border-slate-100 text-slate-500')
                    }
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>
          </section>

          {hasContent && (
            <div className="flex items-center justify-between gap-3 rounded-xl border border-slate-200/80 bg-white px-4 py-3 shadow-sm">
              <span className="flex items-center gap-2 text-sm font-semibold text-slate-600">
                <Clock className="h-4 w-4 text-indigo-500" />
                발표 예상 시간
              </span>
              <span className="text-right">
                <span className="text-base font-bold text-slate-800">
                  {formatMinutes(estimatedMinutes)}
                </span>
                <span className="ml-2 text-[11px] text-slate-400">
                  {estimateBasis}
                </span>
              </span>
            </div>
          )}

          <button
            type="button"
            disabled={!canStart}
            onClick={startSparring}
            className="w-full rounded-xl bg-indigo-600 py-4 text-lg font-semibold text-white shadow-lg shadow-indigo-600/10 transition-all hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            질의응답 스파링 시작 →
          </button>

          <button
            type="button"
            disabled={!hasContent}
            onClick={() => onSkipToReport(buildData())}
            className="w-full rounded-xl border-2 border-slate-200 py-3 text-sm font-semibold text-slate-600 transition-all hover:border-indigo-300 hover:text-indigo-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            질문 없이 결과만 보기
          </button>

          {!canStart && (
            <p className="text-center text-xs text-slate-400">
              {!hasContent
                ? '발표 대본 또는 슬라이드 중 하나는 입력해야 합니다.'
                : personas.length === 0
                  ? '평가자 목록을 먼저 불러와야 합니다. 결과만 보기는 사용할 수 있습니다.'
                  : '청중 페르소나를 1개 이상 선택해주세요. 결과만 보기는 선택 없이 사용할 수 있습니다.'}
            </p>
          )}
        </aside>
      </div>
    </div>
  )
}