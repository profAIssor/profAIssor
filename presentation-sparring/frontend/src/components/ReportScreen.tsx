import {
  Brain,
  Clock3,
  Gauge,
  Lightbulb,
  ListChecks,
  MessageSquareText,
  Mic,
  Pause,
  RotateCcw,
  Shield,
  Target,
  Volume2,
} from 'lucide-react'
import { coverageRate } from '../lib/coverage'
import { loadSessions } from '../lib/sessionStore'
import { formatMinutes } from '../lib/timing'
import { getPersona } from '../personas'
import type {
  AnswerCoaching,
  Report,
  RevisionActionType,
  SpeechMetrics,
  TranscriptTurn,
} from '../types'

interface Props {
  report: Report
  transcript: TranscriptTurn[]
  onRestart: () => void
}

/** 밀리초의 사용자 표시용 초 변환. */
function formatSeconds(milliseconds: number | null): string {
  if (milliseconds == null) return '—'
  return `${(milliseconds / 1000).toFixed(1)}초`
}

/** 음성 지표 신뢰도의 사용자 표시명 변환. */
function confidenceLabel(
  confidence: SpeechMetrics['confidence'],
): string {
  if (confidence === 'high') return '높음'
  if (confidence === 'medium') return '보통'
  return '낮음'
}

export default function ReportScreen({
  report,
  transcript,
  onRestart,
}: Props) {
  const scriptAvailable =
    report.script_available ?? report.word_count > 0
  const slidesAvailable =
    report.slides_available ?? report.slide_coverage.length > 0
  const coverageAvailable =
    report.slide_coverage_available ??
    (scriptAvailable && slidesAvailable)

  // 대본 어절 수 기준 예상 발표 시간 계산
  const estMinutes =
    scriptAvailable && report.word_count > 0
      ? report.word_count / 120
      : 0
  const estSeconds = Math.round(estMinutes * 60)
  const uncovered = coverageAvailable
    ? report.slide_coverage.filter((slide) => !slide.covered)
    : []

  // 현재 세션 저장 이후의 이전 세션 비교
  const previous = loadSessions()[1] ?? null
  const previousScriptAvailable = previous
    ? previous.report.script_available ??
      previous.report.word_count > 0
    : false
  const previousCoverageAvailable = previous
    ? previous.report.slide_coverage_available ??
      previous.report.slide_coverage.length > 0
    : false

  const secondsDelta =
    previous && scriptAvailable && previousScriptAvailable
      ? estSeconds -
        Math.round(previous.estMinutes * 60)
      : null
  const coverageDelta =
    previous && coverageAvailable && previousCoverageAvailable
      ? coverageRate(report.slide_coverage) -
        coverageRate(previous.report.slide_coverage)
      : null

  const speechSummary = report.speech_summary ?? null
  const coachingByTurn = new Map(
    (report.answer_coaching ?? []).map(
      (coaching) => [
        coaching.turn_index,
        coaching,
      ],
    ),
  )

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="rounded-3xl border border-slate-200/80 bg-white p-8 shadow-sm">
        <span className="rounded-full bg-indigo-50 px-3 py-1.5 text-xs font-bold uppercase tracking-wider text-indigo-600">
          AI 심사 결과 보고서
        </span>
        <h1 className="mt-3 text-3xl font-extrabold tracking-tight text-slate-900">
          📋 피드백 리포트
        </h1>
        <p className="mt-2 max-w-xl text-sm leading-relaxed text-slate-500">
          질문마다 어떻게 답했는지, 무엇을 보완하면 좋을지 아래에서
          하나씩 확인하세요.
        </p>
      </div>

      <section className="space-y-4 rounded-2xl border border-slate-200/80 bg-white p-6 shadow-sm">
        <h2 className="flex items-center gap-2 text-lg font-bold text-slate-800">
          <MessageSquareText className="h-5 w-5 text-indigo-600" />
          답변별 상세 교정
        </h2>

        {transcript.length === 0 ? (
          <p className="text-sm text-slate-400">
            기록된 질의응답이 없습니다.
          </p>
        ) : (
          <div className="space-y-3">
            {transcript.map((turn, index) => (
              <TurnCard
                key={index}
                index={index}
                turn={turn}
                coaching={coachingByTurn.get(index)}
              />
            ))}
          </div>
        )}
      </section>

      {speechSummary && (
        <section className="space-y-4 rounded-2xl border border-indigo-100 bg-white p-6 shadow-sm">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-bold text-slate-800">
              <Mic className="h-5 w-5 text-indigo-600" />
              음성 답변 분석
            </h2>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">
              전체 {speechSummary.total_answer_count}개 답변 중{' '}
              {speechSummary.measured_answer_count}개에서 음성을 측정했으며,
              신뢰도가 낮은 답변은 속도·멈춤 판정에서 제외했습니다.
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <SpeechStat
              icon={<Gauge className="h-4 w-4" />}
              label="합산 말 빠르기"
              value={
                speechSummary.session_pace_wpm == null
                  ? '판정 보류'
                  : `${speechSummary.session_pace_wpm.toFixed(1)}어절/분`
              }
            />
            <SpeechStat
              icon={<Pause className="h-4 w-4" />}
              label="긴 멈춤"
              value={`${speechSummary.long_pause_count}회`}
              detail={
                speechSummary.longest_pause_ms == null
                  ? '최장 멈춤 없음'
                  : `최장 ${formatSeconds(
                      speechSummary.longest_pause_ms,
                    )}`
              }
            />
            <SpeechStat
              icon={<Clock3 className="h-4 w-4" />}
              label="평균 답변 착수"
              value={formatSeconds(
                speechSummary.average_initial_latency_ms,
              )}
            />
            <SpeechStat
              icon={<Volume2 className="h-4 w-4" />}
              label="상대 음량 변화"
              value={
                speechSummary.volume_variation_db == null
                  ? '판정 보류'
                  : `${speechSummary.volume_variation_db.toFixed(1)}dB`
              }
            />
          </div>

          {report.speech_delivery_feedback && (
            <div className="rounded-xl border border-indigo-100 bg-indigo-50/50 px-4 py-3 text-sm leading-relaxed text-indigo-950">
              {report.speech_delivery_feedback}
            </div>
          )}

          <p className="text-xs leading-relaxed text-slate-500">
            필러는 Chrome STT 처리 중 명확히 확인된 값만 계산하므로 실제
            사용 횟수보다 적게 표시될 수 있습니다.
          </p>
        </section>
      )}

      <section className="space-y-4 rounded-2xl border border-slate-200/80 bg-white p-6 shadow-sm">
        <h2 className="flex items-center gap-2 text-lg font-bold text-slate-800">
          <Target className="h-5 w-5 text-indigo-600" />
          슬라이드 커버리지
          <span className="text-xs font-normal text-slate-400">
            (슬라이드에 있으나 말로 전달되지 않은 핵심)
          </span>
        </h2>

        {!coverageAvailable ? (
          <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm font-semibold text-slate-600">
            {!scriptAvailable
              ? '발표 대본이 없어 슬라이드의 핵심이 실제 발표에서 전달되었는지 판단하지 못했습니다.'
              : '슬라이드가 없어 대본과 슬라이드의 커버리지를 판단하지 못했습니다.'}
          </div>
        ) : uncovered.length === 0 ? (
          <div className="rounded-xl border border-emerald-100 bg-emerald-50/60 px-4 py-3 text-sm font-semibold text-emerald-700">
            ✅ 모든 슬라이드의 핵심이 대본에서 언급되었습니다.
          </div>
        ) : (
          <div className="space-y-2">
            {uncovered.map((slide) => (
              <div
                key={slide.index}
                className="rounded-xl border border-amber-100 bg-amber-50/60 px-4 py-3"
              >
                <span className="font-bold text-amber-700">
                  슬라이드 {slide.index}
                </span>
                <span className="ml-2 text-sm text-amber-900/80">
                  {slide.missing_point ??
                    '핵심 내용이 대본에서 충분히 언급되지 않았습니다.'}
                </span>
              </div>
            ))}
          </div>
        )}

        {coverageAvailable && (
          <div className="flex flex-wrap gap-2 pt-1">
            {report.slide_coverage.map((slide) => (
              <span
                key={slide.index}
                className={
                  'rounded-lg px-3 py-1 text-xs font-medium ' +
                  (slide.covered
                    ? 'bg-emerald-50 text-emerald-700'
                    : 'bg-amber-50 text-amber-700')
                }
              >
                슬라이드 {slide.index}{' '}
                {slide.covered ? '✓ 전달됨' : '✗ 미언급'}
              </span>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-4 rounded-2xl border border-slate-200/80 bg-white p-6 shadow-sm">
        <h2 className="flex items-center gap-2 text-lg font-bold text-slate-800">
          <ListChecks className="h-5 w-5 text-indigo-600" />
          대본 수정 제안
          <span className="text-xs font-normal text-slate-400">
            (발표 대본에 실제로 적힌 문장만 대상)
          </span>
        </h2>

        {!scriptAvailable ? (
          <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm font-semibold text-slate-600">
            발표 대본이 없어 대본 수정 제안을 제공하지 못했습니다.
          </div>
        ) : !report.revisions || report.revisions.length === 0 ? (
          <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
            발표 대본에서 명확한 수정 지점을 확인하지 못했습니다.
          </div>
        ) : (
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
                  <span className="font-semibold text-slate-500">
                    대본 원문 ·{' '}
                  </span>
                  {revision.observation}
                </p>
                <p className="text-sm text-slate-700">
                  <span className="font-semibold text-slate-500">
                    영향 ·{' '}
                  </span>
                  {revision.impact}
                </p>
                <p className="text-sm text-slate-700">
                  <span className="font-semibold text-slate-500">
                    수정 행동 ·{' '}
                  </span>
                  {revision.action}
                </p>
                <p className="whitespace-pre-wrap rounded-lg bg-white px-3 py-2 text-sm text-indigo-700 shadow-sm">
                  {revision.example}
                </p>
              </div>
            ))}
          </div>
        )}
      </section>

      {report.answer_structure_tip && (
        <div className="flex items-start gap-3 rounded-2xl border border-indigo-100 bg-indigo-50/60 p-4">
          <Lightbulb className="mt-0.5 h-5 w-5 shrink-0 text-indigo-500" />
          <p className="text-sm leading-relaxed text-indigo-900">
            {report.answer_structure_tip}
          </p>
        </div>
      )}

      <section className="space-y-2.5 rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm">
        <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400">
          종합 요약
        </h2>
        <SummaryRow
          icon={<Brain className="h-4 w-4 text-indigo-500" />}
          label="내용"
          body={report.content_feedback}
        />
        <SummaryRow
          icon={<Mic className="h-4 w-4 text-indigo-500" />}
          label="전달"
          body={report.delivery_feedback}
        />
        <SummaryRow
          icon={<Shield className="h-4 w-4 text-indigo-500" />}
          label="대응"
          body={report.response_feedback}
        />
      </section>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Metric
          label="음성 답변 속도"
          value={
            speechSummary?.session_pace_wpm == null
              ? '미측정'
              : `${speechSummary.session_pace_wpm.toFixed(1)}어절/분`
          }
          hint="순수 발화 시간 기준"
        />
        <Metric
          label="명확한 필러"
          value={
            speechSummary
              ? `최소 ${speechSummary.recognized_filler_count}회`
              : '미측정'
          }
          hint="STT 인식 하한선"
        />
        <Metric
          label="총 어절 수"
          value={`${report.word_count}어절`}
          hint="발표 대본 기준"
        />
        <Metric
          label="예상 발표 시간"
          value={
            scriptAvailable
              ? formatMinutes(estMinutes)
              : '—'
          }
          hint={
            scriptAvailable
              ? '약 120어절/분 기준'
              : '발표 대본 없음'
          }
          delta={
            secondsDelta == null
              ? null
              : {
                  value: secondsDelta,
                  goodDirection: 'down',
                  unit: '초',
                }
          }
        />
        <Metric
          label="슬라이드 커버리지"
          value={
            coverageAvailable
              ? `${coverageRate(report.slide_coverage)}%`
              : '—'
          }
          hint={
            coverageAvailable
              ? '대본에서 전달된 비율'
              : !scriptAvailable
                ? '발표 대본 없음'
                : '슬라이드 없음'
          }
          delta={
            coverageDelta == null
              ? null
              : {
                  value: coverageDelta,
                  goodDirection: 'up',
                  unit: '%p',
                }
          }
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

function SummaryRow({
  icon,
  label,
  body,
}: {
  icon: React.ReactNode
  label: string
  body: string
}) {
  return (
    <div className="flex items-start gap-2.5 text-sm">
      <span className="mt-0.5 flex w-14 shrink-0 items-center gap-1.5 whitespace-nowrap font-bold text-slate-700">
        {icon}
        {label}
      </span>
      <p className="flex-1 leading-relaxed text-slate-600">
        {body || '—'}
      </p>
    </div>
  )
}

function TurnCard({
  index,
  turn,
  coaching,
}: {
  index: number
  turn: TranscriptTurn
  coaching?: AnswerCoaching
}) {
  const persona = getPersona(turn.persona_id)
  const rubricEntries = Object.entries(turn.rubric ?? {})
  const hasRetry = Boolean(turn.retry_question)

  return (
    <div className="space-y-3 rounded-xl border border-slate-200/80 bg-slate-50/50 p-4">
      <div className="flex items-center gap-1.5 text-xs font-bold text-indigo-600">
        <span>{persona.emoji}</span>
        {persona.name}
        <span className="font-normal text-slate-400">
          · {index + 1}번째 질문
        </span>
      </div>

      <QuestionAttempt
        label={hasRetry ? '원질문' : '질문'}
        question={turn.question}
        answer={turn.answer}
        metrics={turn.speech_metrics}
      />

      {hasRetry && turn.supplement && (
        <div className="rounded-lg border border-indigo-100 bg-indigo-50/60 px-3 py-2.5">
          <div className="text-[11px] font-bold text-indigo-700">
            제공된 힌트
          </div>
          <p className="mt-1 text-sm leading-relaxed text-slate-700">
            {turn.supplement}
          </p>
          {turn.related_slides &&
            turn.related_slides.length > 0 && (
              <p className="mt-1.5 text-xs text-slate-500">
                관련 발표 자료:{' '}
                {turn.related_slides
                  .map((slide) => `${slide}번 슬라이드`)
                  .join(', ')}
              </p>
            )}
        </div>
      )}

      {hasRetry && turn.retry_question && (
        <QuestionAttempt
          label="쉬운 재질문"
          question={turn.retry_question}
          answer={turn.retry_answer || '(답변 없음)'}
          metrics={turn.retry_speech_metrics}
        />
      )}

      {coaching?.reference_answer ? (
        <div className="rounded-lg border border-emerald-100 bg-emerald-50/70 px-3 py-2.5">
          <div className="text-[11px] font-bold text-emerald-800">
            참고 답변
          </div>
          <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-emerald-950">
            {coaching.reference_answer}
          </p>
          <p className="mt-2 text-xs text-emerald-700">
            발표 자료를 기준으로 구성한 참고용 답변입니다.
          </p>
        </div>
      ) : (
        turn.final_explanation && (
          <div className="rounded-lg border border-amber-100 bg-amber-50 px-3 py-2.5">
            <div className="text-[11px] font-bold text-amber-800">
              개념 정리
            </div>
            <p className="mt-1 text-sm leading-relaxed text-amber-950">
              {turn.final_explanation}
            </p>
            <p className="mt-2 text-xs font-semibold text-amber-800">
              이 질문과 관련된 개념을 발표 전에 다시 학습해 주세요.
            </p>
          </div>
        )
      )}

      <div className="space-y-1.5 rounded-lg bg-white/70 px-3 py-2 text-xs leading-relaxed text-slate-600">
        <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
          최종 평가
        </div>
        <p>{turn.verdict}</p>
        {turn.strengths && <p>✅ {turn.strengths}</p>}
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

function QuestionAttempt({
  label,
  question,
  answer,
  metrics,
}: {
  label: string
  question: string
  answer: string
  metrics?: SpeechMetrics
}) {
  return (
    <div className="space-y-2">
      <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
        {label}
      </div>
      <p className="text-sm font-semibold text-slate-800">
        {question}
      </p>
      <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm leading-relaxed text-slate-600">
        {answer}
      </div>
      {metrics && <TurnSpeechMetrics metrics={metrics} />}

    </div>
  )
}

function TurnSpeechMetrics({ metrics }: { metrics: SpeechMetrics }) {
  return (
    <div className="space-y-2 rounded-lg border border-indigo-100 bg-indigo-50/40 px-3 py-2.5">
      <div className="flex flex-wrap gap-1.5 text-[11px]">
        {metrics.confidence !== 'low' && metrics.pace_wpm != null && (
          <SpeechBadge>
            속도 {metrics.pace_wpm.toFixed(1)}어절/분
          </SpeechBadge>
        )}
        {metrics.confidence !== 'low' &&
          metrics.initial_response_latency_ms != null && (
            <SpeechBadge>
              답변 시작 {formatSeconds(metrics.initial_response_latency_ms)}
            </SpeechBadge>
          )}
        {metrics.confidence !== 'low' && (
          <SpeechBadge>
            긴 멈춤 {metrics.long_pause_count}회
          </SpeechBadge>
        )}
        {metrics.confidence !== 'low' &&
          metrics.longest_pause_ms != null && (
            <SpeechBadge>
              최장 {formatSeconds(metrics.longest_pause_ms)}
            </SpeechBadge>
          )}
        {metrics.confidence !== 'low' &&
          metrics.volume_variation_db != null && (
            <SpeechBadge>
              음량 변화 {metrics.volume_variation_db.toFixed(1)}dB
            </SpeechBadge>
          )}
        <SpeechBadge>
          필러 최소 {metrics.recognized_filler_count}회
        </SpeechBadge>
      </div>

      <p className="text-[11px] leading-relaxed text-slate-500">
        측정 신뢰도 {confidenceLabel(metrics.confidence)}
        {metrics.confidence_reasons.length > 0
          ? ` · ${metrics.confidence_reasons.join(', ')}`
          : ''}
      </p>
    </div>
  )
}

function SpeechBadge({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full border border-indigo-100 bg-white px-2 py-1 font-semibold text-indigo-700">
      {children}
    </span>
  )
}

function SpeechStat({
  icon,
  label,
  value,
  detail,
}: {
  icon: React.ReactNode
  label: string
  value: string
  detail?: string
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-500">
        {icon}
        {label}
      </div>
      <div className="mt-1 text-lg font-bold text-slate-900">
        {value}
      </div>
      {detail && (
        <div className="mt-0.5 text-xs text-slate-400">{detail}</div>
      )}
    </div>
  )
}

interface Delta {
  value: number
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
  const improved =
    delta == null
      ? false
      : delta.goodDirection === 'up'
        ? delta.value > 0
        : delta.value < 0

  return (
    <div className="space-y-1 rounded-2xl border border-slate-200/80 bg-white p-4 text-center shadow-sm">
      <div className="text-xl font-bold text-slate-900">{value}</div>
      <div className="text-xs font-bold text-slate-600">{label}</div>
      <div className="text-[11px] text-slate-400">{hint}</div>

      {delta != null && delta.value !== 0 && (
        <div
          className={
            'pt-1 text-[10px] font-semibold ' +
            (improved ? 'text-emerald-600' : 'text-rose-500')
          }
        >
          {delta.value > 0 ? '▲' : '▼'} {Math.abs(delta.value)}
          {delta.unit} (지난 세션 대비)
        </div>
      )}
    </div>
  )
}