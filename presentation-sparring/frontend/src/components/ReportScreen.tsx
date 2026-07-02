import type { Report } from '../types'

interface Props {
  report: Report
  onRestart: () => void
}

export default function ReportScreen({ report, onRestart }: Props) {
  // Rough speaking-rate estimate: assume ~120 어절/분 delivery pace.
  const estMinutes = report.word_count > 0 ? (report.word_count / 120).toFixed(1) : '0'
  const uncovered = report.slide_coverage.filter((s) => !s.covered)

  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-10">
      <header>
        <h1 className="text-3xl font-bold">📋 피드백 리포트</h1>
        <p className="mt-2 text-slate-400">스파링 세션을 종합한 결과입니다.</p>
      </header>

      {/* axis feedback */}
      <div className="grid gap-4 sm:grid-cols-3">
        <Card title="내용" emoji="🧠" body={report.content_feedback} />
        <Card title="전달" emoji="🗣️" body={report.delivery_feedback} />
        <Card title="대응" emoji="🛡️" body={report.response_feedback} />
      </div>

      {/* slide coverage — the killer feature */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5">
        <h2 className="flex items-center gap-2 text-lg font-semibold">
          🎯 슬라이드 커버리지
          <span className="text-xs font-normal text-slate-400">
            (슬라이드에 있으나 말로 전달되지 않은 핵심)
          </span>
        </h2>

        {uncovered.length === 0 ? (
          <p className="mt-3 text-sm text-emerald-400">
            ✅ 모든 슬라이드의 핵심이 대본에서 언급되었습니다.
          </p>
        ) : (
          <div className="mt-3 space-y-2">
            {uncovered.map((s) => (
              <div
                key={s.index}
                className="rounded-xl border border-amber-600/60 bg-amber-950/30 px-4 py-3"
              >
                <span className="font-semibold text-amber-300">슬라이드 {s.index}</span>
                <span className="ml-2 text-sm text-amber-100/90">
                  {s.missing_point ?? '핵심 내용이 대본에서 충분히 언급되지 않았습니다.'}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* full coverage map */}
        <div className="mt-4 flex flex-wrap gap-2">
          {report.slide_coverage.map((s) => (
            <span
              key={s.index}
              className={
                'rounded-lg px-3 py-1 text-xs font-medium ' +
                (s.covered
                  ? 'bg-emerald-900/40 text-emerald-300'
                  : 'bg-amber-900/50 text-amber-300')
              }
            >
              슬라이드 {s.index} {s.covered ? '✓ 전달됨' : '✗ 미언급'}
            </span>
          ))}
        </div>
      </section>

      {/* delivery metrics */}
      <div className="grid gap-4 sm:grid-cols-3">
        <Metric label="필러 단어" value={`${report.filler_count}회`} hint='"어", "그", "음" 등' />
        <Metric label="총 어절 수" value={`${report.word_count}어절`} hint="대본 기준" />
        <Metric label="예상 발표 시간" value={`~${estMinutes}분`} hint="약 120어절/분 기준" />
      </div>

      <button
        type="button"
        onClick={onRestart}
        className="w-full rounded-xl border border-slate-600 py-3 font-semibold transition hover:border-indigo-500 hover:text-indigo-300"
      >
        새 스파링 시작
      </button>
    </div>
  )
}

function Card({ title, emoji, body }: { title: string; emoji: string; body: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
      <div className="text-sm font-semibold text-indigo-300">
        {emoji} {title}
      </div>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-slate-300">
        {body || '—'}
      </p>
    </div>
  )
}

function Metric({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4 text-center">
      <div className="text-2xl font-bold">{value}</div>
      <div className="mt-1 text-sm text-slate-300">{label}</div>
      <div className="text-xs text-slate-500">{hint}</div>
    </div>
  )
}
