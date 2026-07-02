import { useState } from 'react'
import { fetchReport } from './api'
import ReportScreen from './components/ReportScreen'
import SetupScreen from './components/SetupScreen'
import SparScreen from './components/SparScreen'
import type { PersonaId, Report, Slide, Stage, TranscriptTurn } from './types'

export default function App() {
  const [stage, setStage] = useState<Stage>('setup')
  const [script, setScript] = useState('')
  const [slides, setSlides] = useState<Slide[]>([])
  const [personaIds, setPersonaIds] = useState<PersonaId[]>([])
  const [report, setReport] = useState<Report | null>(null)
  const [reportError, setReportError] = useState<string | null>(null)
  const [loadingReport, setLoadingReport] = useState(false)

  const handleStart = (data: {
    script: string
    slides: Slide[]
    personaIds: PersonaId[]
  }) => {
    setScript(data.script)
    setSlides(data.slides)
    setPersonaIds(data.personaIds)
    setStage('spar')
  }

  const handleFinish = async (transcript: TranscriptTurn[]) => {
    setLoadingReport(true)
    setReportError(null)
    setStage('report')
    try {
      const r = await fetchReport(script, slides, transcript)
      setReport(r)
    } catch (e) {
      setReportError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoadingReport(false)
    }
  }

  const handleRestart = () => {
    setStage('setup')
    setReport(null)
    setReportError(null)
  }

  if (stage === 'setup') {
    return <SetupScreen onStart={handleStart} />
  }

  if (stage === 'spar') {
    return (
      <SparScreen
        script={script}
        slides={slides}
        personaIds={personaIds}
        onFinish={handleFinish}
      />
    )
  }

  // report stage
  if (loadingReport) {
    return (
      <div className="flex h-screen items-center justify-center text-slate-400">
        리포트를 생성하는 중…
      </div>
    )
  }
  if (reportError) {
    return (
      <div className="mx-auto flex h-screen max-w-lg flex-col items-center justify-center gap-4 px-4 text-center">
        <p className="text-rose-400">리포트 생성 실패: {reportError}</p>
        <button
          type="button"
          onClick={handleRestart}
          className="rounded-xl border border-slate-600 px-6 py-2 hover:border-indigo-500"
        >
          처음으로
        </button>
      </div>
    )
  }
  if (report) {
    return <ReportScreen report={report} onRestart={handleRestart} />
  }
  return null
}
