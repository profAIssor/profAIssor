import { Brain, Lightbulb, ListChecks, MessageSquareText, Mic, RotateCcw, Shield, Target } from 'lucide-react'
import { coverageRate } from '../lib/coverage'
import { loadSessions } from '../lib/sessionStore'
import { formatMinutes } from '../lib/timing'
import { getPersona } from '../personas'
import type { Report, RevisionActionType, TranscriptTurn } from '../types'

interface Props {
  report: Report
  transcript: TranscriptTurn[]
  onRestart: () => void
}

export default function ReportScreen({ report, transcript, onRestart }: Props) {
  // Rough speaking-rate estimate: assume ~120 어절/분 delivery pace.
  const estMinutes = report.word_count > 0 ? report.word_count / 120 : 0
  const estSeconds = Math.round(estMinutes * 60)
  const uncovered = report.slide_coverage.filter((s) => !s.covered)

  // sessions[0] is this just-completed session (saveSession runs right
  // before this screen renders) — sessions[1] is the one to compare against.
  const previous = loadSessions()[1] ?? null
  const fillerDelta = previous ? report.filler_count - previous.report.filler_count : null
  // 델타도 초 단위로 비교해 "0.1분" 같은 추상적 표기를 피한다.
  const secondsDelta = previous ? estSeconds - Math.round(previous.estMinutes * 60) : null
  const coverageDelta = previous
    ? coverageRate(report.slide_coverage) - coverageRate(previous.report.slide_coverage)
    : null

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      {/* Hero banner */}
      <div className="rounded-3xl border border-slate-200/80 bg-white p-8 shadow-sm">
        <span className="rounded-full bg-indigo-50 px-3 py-1.5 text-xs font-bold uppercase tracking-wider text-indigo-600">
          AI 심사 결과 보고서
        </span>
        <h1 className="mt-3 text-3xl font-extrabold tracking-tight text-slate-900">📋 피드백 리포트</h1>
        <p className="mt-2 max-w-xl text-sm leading-relaxed text-slate-500">
          질문마다 어떻게 답했는지, 무엇을 보완하면 좋을지 아래에서 하나씩 확인하세요.
        </p>
      </div>

      {/* per-turn detail — the main content of the report */}
      <section className="space-y-4 rounded-2xl border border-slate-200/80 bg-white p-6 shadow-sm">
        <h2 className="flex items-center gap-2 text-lg font-bold text-slate-800">
          <MessageSquareText className="h-5 w-5 text-indigo-600" />
          답변별 상세 교정
        </h2>

        {transcript.length === 0 ? (
          <p className="text-sm text-slate-400">기록된 질의응답이 없습니다.</p>
        ) : (
          <div className="space-y-3">
            {transcript.map((turn, i) => (
              <TurnCard key={i} index={i} turn={turn} />
            ))}
          </div>
        )}
      </section>

      {/* slide coverage — the killer feature */}
      <section className="space-y-4 rounded-2xl border border-slate-200/80 bg-white p-6 shadow-sm">
        <h2 className="flex items-center gap-2 text-lg font-bold text-slate-800">
          <Target className="h-5 w-5 text-indigo-600" />
          슬라이드 커버리지
          <span className="text-xs font-normal text-slate-400">
            (슬라이드에 있으나 말로 전달되지 않은 핵심)
          </span>
        </h2>

        {uncovered.length === 0 ? (
          <div className="rounded-xl border border-emerald-100 bg-emerald-50/60 px-4 py-3 text-sm font-semibold text-emerald-700">
            ✅ 모든 슬라이드의 핵심이 대본에서 언급되었습니다.
          </div>
        ) : (
          <div className="space-y-2">
            {uncovered.map((s) => (
              <div key={s.index} className="rounded-xl border border-amber-100 bg-amber-50/60 px-4 py-3">
                <span className="font-bold text-amber-700">슬라이드 {s.index}</span>
                <span className="ml-2 text-sm text-amber-900/80">
                  {s.missing_point ?? '핵심 내용이 대본에서 충분히 언급되지 않았습니다.'}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* full coverage map */}
        <div className="flex flex-wrap gap-2 pt-1">
          {report.slide_coverage.map((s) => (
            <span
              key={s.index}
              className={
                'rounded-lg px-3 py-1 text-xs font-medium ' +
                (s.covered ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700')
              }
            >
              슬라이드 {s.index} {s.covered ? '✓ 전달됨' : '✗ 미언급'}
            </span>
          ))}
        </div>
      </section>

      {/* concrete revision suggestions — 1-4C
          답변별 상세 교정(과거 기록)과 달리 앞으로의 대본 교정안이므로 별도 유지 */}
      {report.revisions && report.revisions.length > 0 && (
        <section className="space-y-4 rounded-2xl border border-slate-200/80 bg-white p-6 shadow-sm">
          <h2 className="flex items-center gap-2 text-lg font-bold text-slate-800">
            <ListChecks className="h-5 w-5 text-indigo-600" />
            대본 수정 제안
            <span className="text-xs font-normal text-slate-400">
              (관찰 → 영향 → 수정 행동 → 예시 순서)
            </span>
          </h2>

          <div className="space-y-3">
            {report.revisions.map((revision, index) => (
              <div
                key={index}
                className="space-y-2 rounded-xl border border-slate-200/80 bg-slate-50/60 p-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-indigo-100 px-2.5 py-0.5 text-xs font-bold text-indigo-700">
                    {ACTION_TYPE_LABEL[revision.action_type]}
                  </span>
                  {revision.slide_index != null && (
                    <span className="text-xs font-semibold text-slate-400">
                      슬라이드 {revision.slide_index}
                    </span>
                  )}
                </div>

                <p className="text-sm text-slate-700">
                  <span className="font-semibold text-slate-500">관찰 · </span>
                  {revision.observation}
                </p>
                <p className="text-sm text-slate-700">
                  <span className="font-semibold text-slate-500">영향 · </span>
                  {revision.impact}
                </p>
                <p className="text-sm text-slate-700">
                  <span className="font-semibold text-slate-500">수정 행동 · </span>
                  {revision.action}
                </p>
                <p className="whitespace-pre-wrap rounded-lg bg-white px-3 py-2 text-sm text-indigo-700 shadow-sm">
                  {revision.example}
                </p>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* recommended answer structure — 1-4C */}
      {report.answer_structure_tip && (
        <div className="flex items-start gap-3 rounded-2xl border border-indigo-100 bg-indigo-50/60 p-4">
          <Lightbulb className="mt-0.5 h-5 w-5 shrink-0 text-indigo-500" />
          <p className="text-sm leading-relaxed text-indigo-900">{report.answer_structure_tip}</p>
        </div>
      )}

      {/* condensed axis summary — main(PR#15): 상세 교정이 메인이므로 축약 표시 */}
      <section className="space-y-2.5 rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm">
        <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400">종합 요약</h2>
        <SummaryRow icon={<Brain className="h-4 w-4 text-indigo-500" />} label="내용" body={report.content_feedback} />
        <SummaryRow icon={<Mic className="h-4 w-4 text-indigo-500" />} label="전달" body={report.delivery_feedback} />
        <SummaryRow icon={<Shield className="h-4 w-4 text-indigo-500" />} label="대응" body={report.response_feedback} />
      </section>

      {/* delivery metrics */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Metric
          label="필러 단어"
          value={`${report.filler_count}회`}
          hint='"어", "그", "음" 등'
          delta={fillerDelta == null ? null : { value: fillerDelta, goodDirection: 'down', unit: '회' }}
        />
        <Metric label="총 어절 수" value={`${report.word_count}어절`} hint="대본 기준" />
        <Metric
          label="예상 발표 시간"
          value={formatMinutes(estMinutes)}
          hint="약 120어절/분 기준"
          delta={secondsDelta == null ? null : { value: secondsDelta, goodDirection: 'down', unit: '초' }}
        />
        <Metric
          label="슬라이드 커버리지"
          value={`${coverageRate(report.slide_coverage)}%`}
          hint="말로 전달된 비율"
          delta={coverageDelta == null ? null : { value: coverageDelta, goodDirection: 'up', unit: '%p' }}
        />
      </div>

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

const ACTION_TYPE_LABEL: Record<RevisionActionType, string> = {
  sentence_split: '문장 분리',
  signal_phrase: '신호 문장 추가',
  emphasis_shift: '강조 위치 이동',
  term_explanation: '용어 설명 추가',
  other: '수정 제안',
}

function SummaryRow({ icon, label, body }: { icon: React.ReactNode; label: string; body: string }) {
  return (
    <div className="flex items-start gap-2.5 text-sm">
      <span className="mt-0.5 flex w-14 shrink-0 items-center gap-1.5 whitespace-nowrap font-bold text-slate-700">
        {icon}
        {label}
      </span>
      <p className="flex-1 leading-relaxed text-slate-600">{body || '—'}</p>
    </div>
  )
}

function TurnCard({ index, turn }: { index: number; turn: TranscriptTurn }) {
  const persona = getPersona(turn.persona_id)
  const rubricEntries = Object.entries(turn.rubric ?? {})

  return (
    <div className="space-y-2.5 rounded-xl border border-slate-200/80 bg-slate-50/50 p-4">
      <div className="flex items-center gap-1.5 text-xs font-bold text-indigo-600">
        <span>{persona.emoji}</span>
        {persona.name}
        <span className="font-normal text-slate-400">· {index + 1}번째 질문</span>
      </div>

      <p className="text-sm font-semibold text-slate-800">{turn.question}</p>

      <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm leading-relaxed text-slate-600">
        {turn.answer}
      </div>

      <div className="space-y-1.5 rounded-lg bg-white/70 px-3 py-2 text-xs leading-relaxed text-slate-600">
        <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">총평</div>
        <p>{turn.verdict}</p>
        <p>✅ {turn.strengths}</p>
        <p>⚠️ {turn.gaps}</p>
      </div>

      {rubricEntries.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-0.5">
          {rubricEntries.map(([axis, value]) => (
            <span
              key={axis}
              className={
                'rounded-full px-2 py-0.5 text-[10px] font-semibold ' +
                (value === '우수'
                  ? 'bg-emerald-50 text-emerald-700'
                  : value === '보통'
                    ? 'bg-amber-50 text-amber-700'
                    : 'bg-rose-50 text-rose-700')
              }
            >
              {axis} {value}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

interface Delta {
  value: number
  /** Which direction of change counts as an improvement. */
  goodDirection: 'up' | 'down'
  unit: string
}

function Metric({
  label,
  value,
  hint,
  delta,
}: {
  label: string
  value: string
  hint: string
  delta?: Delta | null
}) {
  return (
    <div className="space-y-1 rounded-2xl border border-slate-200/80 bg-white p-4 text-center shadow-sm">
      <div className="text-2xl font-bold text-slate-900">{value}</div>
      <div className="text-sm font-medium text-slate-600">{label}</div>
      <div className="text-xs text-slate-400">{hint}</div>
      {delta != null && delta.value !== 0 && (
        <div
          className={
            'text-xs font-semibold ' +
            ((delta.value < 0) === (delta.goodDirection === 'down') ? 'text-emerald-600' : 'text-rose-600')
          }
        >
          {delta.value > 0 ? '▲' : '▼'} {Math.abs(delta.value)}
          {delta.unit} (지난 세션 대비)
        </div>
      )}
    </div>
  )
}