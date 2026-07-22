import { RotateCcw, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { coverageRate } from '../lib/coverage'
import {
  clearSessions,
  deleteSession,
  type SessionRecord,
} from '../lib/sessionStore'
import { formatMinutes } from '../lib/timing'

interface Props {
  sessions: SessionRecord[]
  onRestart: () => void
}

/** 세션 완료 시각의 축약 표시. */
function shortDate(iso: string): string {
  const date = new Date(iso)
  return `${date.getMonth() + 1}/${date.getDate()} ${date.getHours()}:${String(
    date.getMinutes(),
  ).padStart(2, '0')}`
}

/** 세션 음성 지표의 목록 표시 문자열 생성. */
function speechSummaryText(session: SessionRecord): string | null {
  const summary = session.report.speech_summary
  if (!summary) return null

  const parts = [
    `음성 측정 ${summary.measured_answer_count}/${summary.total_answer_count}답변`,
  ]

  if (summary.session_pace_wpm != null) {
    parts.push(`답변 속도 ${summary.session_pace_wpm.toFixed(1)}어절/분`)
  }

  parts.push(`필러 최소 ${summary.recognized_filler_count}회`)
  return parts.join(' · ')
}

/** 로컬 세션 히스토리와 비교 추이 화면. */
export default function HistoryScreen({
  sessions: initialSessions,
  onRestart,
}: Props) {
  const [sessions, setSessions] = useState(initialSessions)

  const handleDelete = (id: string) => {
    deleteSession(id)
    setSessions((previous) =>
      previous.filter((session) => session.id !== id),
    )
  }

  const handleClearAll = () => {
    if (
      !window.confirm(
        '모든 히스토리 기록을 삭제할까요? 되돌릴 수 없습니다.',
      )
    ) {
      return
    }

    clearSessions()
    setSessions([])
  }

  // 최신순 저장 데이터를 시간순 차트 데이터로 변환
  const chartData = [...sessions].reverse().map((session) => ({
    label: shortDate(session.completedAt),
    '예상시간(초)': Math.round(session.estMinutes * 60),
    커버리지: coverageRate(session.report.slide_coverage),
  }))

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex flex-col gap-3 rounded-3xl border border-slate-200/80 bg-white p-6 shadow-sm sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-extrabold text-slate-900">
            히스토리
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            로그인이나 별도 DB 없이 이 브라우저의 localStorage에 저장된
            기록입니다.
          </p>
        </div>

        {sessions.length > 0 && (
          <button
            type="button"
            onClick={handleClearAll}
            className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-rose-200 px-3 py-2 text-xs font-semibold text-rose-600 transition hover:bg-rose-50"
          >
            <Trash2 className="h-3.5 w-3.5" />
            전체 삭제
          </button>
        )}
      </div>

      {sessions.length === 0 ? (
        <div className="rounded-2xl border border-slate-200 bg-white p-10 text-center text-sm text-slate-400 shadow-sm">
          아직 완료된 세션이 없습니다.
        </div>
      ) : (
        <>
          {sessions.length >= 2 && (
            <section className="space-y-3 rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm">
              <div>
                <h2 className="text-lg font-bold text-slate-800">추이</h2>
                <p className="mt-1 text-xs text-slate-500">
                  슬라이드 커버리지(%)와 예상 발표 시간(초) 비교입니다.
                  필러는 STT 인식 하한선이므로 세션 간 증감 차트에서
                  제외했습니다.
                </p>
              </div>

              <div className="h-72 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={chartData}
                    margin={{ top: 10, right: 18, left: -12, bottom: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="label" fontSize={11} />
                    <YAxis fontSize={11} />
                    <Tooltip />
                    <Line
                      type="monotone"
                      dataKey="커버리지"
                      stroke="#4f46e5"
                      strokeWidth={2}
                      dot={{ r: 3 }}
                    />
                    <Line
                      type="monotone"
                      dataKey="예상시간(초)"
                      stroke="#16a34a"
                      strokeWidth={2}
                      dot={{ r: 3 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </section>
          )}

          <section className="space-y-3 rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm">
            <h2 className="text-lg font-bold text-slate-800">완료 기록</h2>

            <div className="space-y-2">
              {sessions.map((session) => {
                const speechText = speechSummaryText(session)

                return (
                  <div
                    key={session.id}
                    className="flex items-start justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50/50 px-4 py-3"
                  >
                    <div className="min-w-0">
                      <div className="text-sm font-bold text-slate-800">
                        {shortDate(session.completedAt)}
                      </div>
                      <p className="mt-1 text-xs leading-relaxed text-slate-500">
                        전공계열: {session.field ?? '미지정'} · 어절 수:{' '}
                        {session.report.word_count} · 예상 발표 시간:{' '}
                        {formatMinutes(session.estMinutes)} · 커버리지:{' '}
                        {coverageRate(session.report.slide_coverage)}%
                      </p>
                      {speechText && (
                        <p className="mt-1 text-xs leading-relaxed text-indigo-600">
                          {speechText}
                        </p>
                      )}
                    </div>

                    <button
                      type="button"
                      onClick={() => handleDelete(session.id)}
                      aria-label="이 기록 삭제"
                      className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-slate-200 text-slate-400 transition hover:border-rose-400 hover:text-rose-500"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )
              })}
            </div>
          </section>
        </>
      )}

      <button
        type="button"
        onClick={onRestart}
        className="flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 py-3.5 text-sm font-bold text-white shadow-md shadow-indigo-600/10 transition-colors hover:bg-indigo-700"
      >
        <RotateCcw className="h-4 w-4" />
        새 스파링 시작
      </button>
    </div>
  )
}