import { lazy, Suspense, useState } from 'react'
import { fetchReport } from './api'
import ReportScreen from './components/ReportScreen'
import SetupScreen from './components/SetupScreen'
import SparScreen from './components/SparScreen'
import { loadSessions, saveSession } from './lib/sessionStore'
import type { AcademicField, Difficulty, PersonaId, Report, Slide, Stage, TranscriptTurn } from './types'

// recharts pulls in a sizable chart library — only load it when the user
// actually visits the history screen, not on the initial setup/spar bundle.
const HistoryScreen = lazy(() => import('./components/HistoryScreen'))

// The wizard stepper covers setup→spar→report; 'history' is a separate,
// always-available nav item outside this flow.
const STEP_LABELS: Record<Exclude<Stage, 'history'>, string> = {
  setup: '1. 발표 자료 등록',
  spar: '2. 꼬리 질문 스파링',
  report: '3. 종합 피드백 리포트',
}
const STEP_ORDER: Exclude<Stage, 'history'>[] = ['setup', 'spar', 'report']

export default function App() {
  const [stage, setStage] = useState<Stage>('setup')
  const [script, setScript] = useState('')
  const [slides, setSlides] = useState<Slide[]>([])
  const [personaIds, setPersonaIds] = useState<PersonaId[]>([])
  const [difficulty, setDifficulty] = useState<Difficulty>('medium')
  const [maxTurns, setMaxTurns] = useState(2)
  const [field, setField] = useState<AcademicField | null>(null)
  const [report, setReport] = useState<Report | null>(null)
  const [transcript, setTranscript] = useState<TranscriptTurn[]>([])
  const [reportError, setReportError] = useState<string | null>(null)
  const [loadingReport, setLoadingReport] = useState(false)

  const handleStart = (data: {
    script: string
    slides: Slide[]
    personaIds: PersonaId[]
    difficulty: Difficulty
    maxTurns: number
    field: AcademicField | null
  }) => {
    setScript(data.script)
    setSlides(data.slides)
    setPersonaIds(data.personaIds)
    setDifficulty(data.difficulty)
    setMaxTurns(data.maxTurns)
    setField(data.field)
    setStage('spar')
  }

  const handleFinish = async (finishedTranscript: TranscriptTurn[]) => {
    setLoadingReport(true)
    setReportError(null)
    setTranscript(finishedTranscript)
    setStage('report')
    try {
      const r = await fetchReport(script, slides, finishedTranscript, field)
      setReport(r)
      saveSession({
        field,
        personaIds,
        report: r,
        estMinutes: r.word_count > 0 ? r.word_count / 120 : 0,
      })
    } catch (e) {
      setReportError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoadingReport(false)
    }
  }

  const handleRestart = () => {
    setStage('setup')
    setReport(null)
    setTranscript([])
    setReportError(null)
  }

  const currentStepIdx = stage === 'history' ? -1 : STEP_ORDER.indexOf(stage)
  const historySessions = stage === 'history' ? loadSessions() : []

  return (
    <div className="flex min-h-screen flex-col bg-[#F9FAFB] font-sans text-slate-900 selection:bg-indigo-100">
      {/* Header */}
      <header className="z-30 flex h-16 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-6 shadow-sm sm:px-8">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleRestart}
            className="flex h-8 w-8 items-center justify-center rounded-lg bg-black"
            aria-label="처음으로"
          >
            <div className="h-4 w-4 rotate-45 border-2 border-white" />
          </button>
          <button type="button" onClick={handleRestart} className="text-lg font-extrabold tracking-tight">
            prof<span className="text-indigo-600">AI</span>ssor
          </button>
          <span className="ml-1.5 rounded bg-slate-100 px-2 py-0.5 text-[10px] font-bold text-slate-500">
            발표 스파링 파트너
          </span>
        </div>

        <div className="flex items-center gap-4 sm:gap-6">
          <nav className="hidden items-center gap-4 text-xs font-semibold text-slate-400 sm:flex sm:gap-6">
            {STEP_ORDER.map((s, i) => (
              <span
                key={s}
                className={
                  'flex items-center gap-2 transition-colors ' +
                  (i === currentStepIdx ? 'text-black' : i < currentStepIdx ? 'text-indigo-600' : '')
                }
              >
                <span
                  className={
                    'flex h-4 w-4 items-center justify-center rounded-full border text-[9px] font-bold ' +
                    (i <= currentStepIdx
                      ? 'border-indigo-600 bg-indigo-600 text-white'
                      : 'border-slate-300 text-slate-400')
                  }
                >
                  {i + 1}
                </span>
                {STEP_LABELS[s].replace(/^\d+\.\s*/, '')}
              </span>
            ))}
          </nav>
          <button
            type="button"
            onClick={() => setStage('history')}
            className={
              'rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors ' +
              (stage === 'history'
                ? 'border-indigo-600 bg-indigo-50 text-indigo-700'
                : 'border-slate-200 text-slate-500 hover:border-indigo-300 hover:text-indigo-600')
            }
          >
            히스토리
          </button>
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 px-4 py-8 sm:px-8 sm:py-10">
        {stage === 'setup' && <SetupScreen onStart={handleStart} />}

        {stage === 'spar' && (
          <SparScreen
            script={script}
            slides={slides}
            personaIds={personaIds}
            difficulty={difficulty}
            maxTurns={maxTurns}
            field={field}
            onFinish={handleFinish}
          />
        )}

        {stage === 'report' && (
          <>
            {loadingReport && (
              <div className="mx-auto flex max-w-3xl flex-col items-center justify-center gap-4 py-24 text-center">
                <div className="relative h-10 w-10">
                  <div className="absolute inset-0 rounded-full border-4 border-indigo-100" />
                  <div className="absolute inset-0 animate-spin rounded-full border-4 border-t-indigo-600" />
                </div>
                <p className="text-sm font-bold text-indigo-600">리포트를 생성하는 중…</p>
              </div>
            )}
            {!loadingReport && reportError && (
              <div className="mx-auto flex max-w-lg flex-col items-center justify-center gap-4 px-4 py-24 text-center">
                <p className="text-sm font-semibold text-rose-600">리포트 생성 실패: {reportError}</p>
                <button
                  type="button"
                  onClick={handleRestart}
                  className="rounded-xl border border-slate-200 bg-white px-6 py-2.5 text-sm font-semibold text-slate-700 shadow-sm hover:border-indigo-300 hover:text-indigo-600"
                >
                  처음으로
                </button>
              </div>
            )}
            {!loadingReport && !reportError && report && (
              <ReportScreen report={report} transcript={transcript} onRestart={handleRestart} />
            )}
          </>
        )}

        {stage === 'history' && (
          <Suspense fallback={<p className="text-center text-sm text-slate-400">불러오는 중…</p>}>
            <HistoryScreen sessions={historySessions} onRestart={handleRestart} />
          </Suspense>
        )}
      </main>

      {/* Footer */}
      <footer className="flex h-10 shrink-0 items-center justify-between border-t border-slate-200 bg-white px-6 text-[11px] text-slate-400">
        <span>© 2026 profAIssor. All rights reserved.</span>
        <span className="hidden sm:inline">마이크 사용 시 STT 받아쓰기를 지원합니다</span>
      </footer>
    </div>
  )
}
