import { RotateCcw } from 'lucide-react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { coverageRate } from '../lib/coverage'
import type { SessionRecord } from '../lib/sessionStore'
import { formatMinutes } from '../lib/timing'

interface Props {
  sessions: SessionRecord[]
  onRestart: () => void
}

function shortDate(iso: string): string {
  const d = new Date(iso)
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** Session history: a chronological trend chart (2+ sessions) + a full list. */
export default function HistoryScreen({ sessions, onRestart }: Props) {
  // Stored newest-first; the chart reads left-to-right chronologically.
  const chartData = [...sessions].reverse().map((s) => ({
    label: shortDate(s.completedAt),
    필러: s.report.filler_count,
    // 초 단위로 표시 — 분 단위(0.2 등)는 축 바닥에 깔려 추이가 안 보임
    '예상시간(초)': Math.round(s.estMinutes * 60),
    커버리지: coverageRate(s.report.slide_coverage),
  }))

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <h1 className="text-2xl font-extrabold tracking-tight text-slate-900">히스토리</h1>

      {sessions.length === 0 ? (
        <p className="text-sm text-slate-500">아직 완료된 세션이 없습니다.</p>
      ) : (
        <>
          {sessions.length >= 2 && (
            <section className="rounded-2xl border border-slate-200/80 bg-white p-6 shadow-sm">
              <h2 className="mb-4 text-sm font-bold text-slate-800">추이</h2>
              <div className="h-64 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartData} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="label" tick={{ fontSize: 11 }} stroke="#94a3b8" />
                    <YAxis tick={{ fontSize: 11 }} stroke="#94a3b8" />
                    <Tooltip />
                    <Line type="monotone" dataKey="필러" stroke="#f43f5e" strokeWidth={2} dot={{ r: 3 }} />
                    <Line type="monotone" dataKey="커버리지" stroke="#4f46e5" strokeWidth={2} dot={{ r: 3 }} />
                    <Line type="monotone" dataKey="예상시간(초)" stroke="#10b981" strokeWidth={2} dot={{ r: 3 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-2 text-xs text-slate-400">
                필러(빨강, 회) · 슬라이드 커버리지(남색, %) · 예상 발표시간(초록, 초)
              </p>
            </section>
          )}

          <ul className="space-y-2">
            {sessions.map((s) => (
              <li key={s.id} className="rounded-xl border border-slate-200/80 bg-white p-4 text-sm shadow-sm">
                <div className="font-semibold text-slate-800">{shortDate(s.completedAt)}</div>
                <div className="mt-1 text-xs text-slate-500">
                  전공계열: {s.field ?? '미지정'} · 어절 수: {s.report.word_count} · 필러: {s.report.filler_count}회 ·
                  예상 발표 시간: {formatMinutes(s.estMinutes)} · 커버리지: {coverageRate(s.report.slide_coverage)}%
                </div>
              </li>
            ))}
          </ul>
        </>
      )}

      <button
        type="button"
        onClick={onRestart}
        className="flex w-full items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white py-3.5 text-sm font-bold text-slate-700 shadow-sm hover:border-indigo-300 hover:text-indigo-600"
      >
        <RotateCcw className="h-4 w-4" />
        새 스파링 시작
      </button>
    </div>
  )
}
