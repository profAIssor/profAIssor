import { Mic, Send, Square } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { evaluateAnswer, fetchQuestion } from '../api'
import { useSpeechRecognition } from '../hooks/useSpeechRecognition'
import { buildTermDictionary, correctText } from '../lib/termCorrection'
import { getPersona } from '../personas'
import type { AcademicField, ChatMessage, Difficulty, PersonaId, Slide, TranscriptTurn } from '../types'

interface Props {
  script: string
  slides: Slide[]
  personaIds: PersonaId[]
  difficulty: Difficulty
  maxTurns: number
  field: AcademicField | null
  onFinish: (transcript: TranscriptTurn[]) => void
}

export default function SparScreen({
  script,
  slides,
  personaIds,
  difficulty,
  maxTurns,
  field,
  onFinish,
}: Props) {
  const [personaIndex, setPersonaIndex] = useState(0)
  const [turn, setTurn] = useState(0)
  const [question, setQuestion] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [answer, setAnswer] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [interim, setInterim] = useState('')

  const transcriptRef = useRef<TranscriptTurn[]>([])
  const startedRef = useRef(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Presentation-specific term dictionary (script + slides) used to correct
  // likely STT mishearings of technical terms — built once per session.
  const termDict = useMemo(() => buildTermDictionary(script, slides), [script, slides])

  // 🎙 STT: dictation appends recognized text into the answer box (additive —
  // the text loop is unchanged; the user can still type/edit before sending).
  const {
    supported: sttSupported,
    listening,
    toggle: toggleMic,
    stop: stopMic,
  } = useSpeechRecognition({
    onFinal: (text) => {
      if (!text) return
      const corrected = correctText(text, termDict)
      setAnswer((prev) => (prev.trim() ? prev.trimEnd() + ' ' : '') + corrected)
    },
    onInterim: setInterim,
  })

  const activePersonaId = personaIds[personaIndex]
  const persona = getPersona(activePersonaId)

  const pushMessage = (m: ChatMessage) => setMessages((prev) => [...prev, m])

  // Fetch the first (turn-0) question for a given persona.
  const loadFirstQuestion = async (pIndex: number) => {
    setBusy(true)
    setError(null)
    try {
      const pid = personaIds[pIndex]
      const q = await fetchQuestion(script, slides, pid, difficulty, field)
      setQuestion(q.question)
      pushMessage({ role: 'question', personaId: pid, text: q.question })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  // Kick off the very first question once (guard against StrictMode double-run).
  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true
    void loadFirstQuestion(0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const submit = async () => {
    if (!question || !answer.trim() || busy) return
    stopMic()
    setInterim('')
    const pid = activePersonaId
    const q = question
    const currentTurn = turn
    setBusy(true)
    setError(null)
    pushMessage({ role: 'answer', personaId: pid, text: answer })
    const studentAnswer = answer
    setAnswer('')

    try {
      const ev = await evaluateAnswer({
        script,
        personaId: pid,
        question: q,
        answer: studentAnswer,
        turn: currentTurn,
        maxTurns,
        field,
        termHints: termDict,
      })
      pushMessage({
        role: 'verdict',
        personaId: pid,
        text: `평가: ${ev.verdict}\n👍 ${ev.strengths}\n⚠️ ${ev.gaps}`,
        rubric: ev.rubric,
      })
      transcriptRef.current.push({
        persona_id: pid,
        question: q,
        answer: studentAnswer,
        verdict: ev.verdict,
        gaps: ev.gaps,
      })

      if (ev.followup) {
        // Same persona digs deeper.
        setQuestion(ev.followup)
        setTurn(currentTurn + 1)
        pushMessage({ role: 'question', personaId: pid, text: ev.followup })
        setBusy(false)
      } else {
        // Rotate to the next persona, or finish.
        const nextIdx = personaIndex + 1
        if (nextIdx < personaIds.length) {
          setPersonaIndex(nextIdx)
          setTurn(0)
          setQuestion(null)
          await loadFirstQuestion(nextIdx)
        } else {
          onFinish(transcriptRef.current)
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      void submit()
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      {/* Persona banner + progress */}
      <div className="flex items-center justify-between rounded-2xl border border-slate-200/80 bg-white px-5 py-3.5 shadow-sm">
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 select-none items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-lg">
            {persona.emoji}
          </span>
          <div>
            <div className="text-sm font-bold text-slate-800">{persona.name}</div>
            <div className="text-xs text-slate-400">현재 상대 페르소나</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {personaIds.map((id, i) => (
            <span
              key={id}
              className={
                'h-2 w-8 rounded-full ' +
                (i < personaIndex
                  ? 'bg-indigo-600'
                  : i === personaIndex
                    ? 'animate-pulse bg-indigo-400'
                    : 'bg-slate-200')
              }
              title={getPersona(id).name}
            />
          ))}
          <span className="ml-2 text-xs font-semibold text-slate-400">
            {personaIndex + 1} / {personaIds.length}
          </span>
        </div>
      </div>

      {/* chat log */}
      <div
        ref={scrollRef}
        className="flex h-[420px] flex-col space-y-4 overflow-y-auto rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm"
      >
        {messages.map((m, i) => {
          const p = getPersona(m.personaId)
          if (m.role === 'answer') {
            return (
              <div key={i} className="flex justify-end">
                <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-tr-sm bg-indigo-600 px-4 py-2.5 text-sm text-white shadow-sm">
                  {m.text}
                </div>
              </div>
            )
          }
          if (m.role === 'verdict') {
            const rubricEntries = m.rubric ? Object.entries(m.rubric) : []
            return (
              <div key={i} className="flex justify-center">
                <div className="w-full max-w-[90%] space-y-2 rounded-xl border border-slate-100 bg-slate-50 px-4 py-2.5 text-xs leading-relaxed text-slate-600">
                  <div className="whitespace-pre-wrap">{m.text}</div>
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
              </div>
            )
          }
          return (
            <div key={i} className="flex justify-start">
              <div className="max-w-[80%] rounded-2xl rounded-tl-sm border border-slate-200 bg-white px-4 py-2.5 text-sm shadow-sm">
                <div className="mb-1 flex items-center gap-1 text-xs font-bold text-indigo-600">
                  <span>{p.emoji}</span>
                  {p.name}
                </div>
                <span className="whitespace-pre-wrap text-slate-700">{m.text}</span>
              </div>
            </div>
          )
        })}
        {busy && (
          <div className="flex justify-start">
            <div className="flex items-center gap-2 rounded-2xl rounded-tl-sm border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-400 shadow-sm">
              생각 중…
              <div className="flex gap-1">
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-indigo-600" style={{ animationDelay: '0ms' }} />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-indigo-600" style={{ animationDelay: '150ms' }} />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-indigo-600" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-xl border border-rose-100 bg-rose-50 px-4 py-2.5 text-sm text-rose-600">
          오류: {error}
        </div>
      )}

      {/* live dictation preview */}
      {listening && (
        <div className="flex items-center gap-2 text-xs text-indigo-600">
          <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-rose-500" />
          받아쓰는 중… <span className="text-slate-400">{interim || '(말해보세요)'}</span>
        </div>
      )}

      {/* answer input */}
      <div className="flex gap-2 rounded-2xl border border-slate-200/80 bg-white p-3 shadow-sm">
        {sttSupported && (
          <button
            type="button"
            data-testid="mic-btn"
            onClick={toggleMic}
            disabled={busy || !question}
            title={listening ? '받아쓰기 중지' : '음성으로 답변 (STT)'}
            className={
              'flex h-auto w-12 shrink-0 items-center justify-center rounded-xl border transition disabled:cursor-not-allowed disabled:opacity-40 ' +
              (listening
                ? 'border-rose-300 bg-rose-50 text-rose-500'
                : 'border-slate-200 bg-slate-50 text-slate-500 hover:border-indigo-400 hover:text-indigo-600')
            }
          >
            {listening ? (
              <Square className="h-4 w-4 fill-current" />
            ) : (
              <Mic className="h-4 w-4" />
            )}
          </button>
        )}
        <textarea
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={busy || !question}
          rows={2}
          placeholder={
            sttSupported
              ? '답변을 입력하거나 마이크 버튼으로 말하세요… (Ctrl/⌘ + Enter 로 전송)'
              : '답변을 입력하세요… (Ctrl/⌘ + Enter 로 전송)'
          }
          className="flex-1 resize-none rounded-xl border border-slate-200 bg-slate-50/50 px-4 py-3 text-sm text-slate-700 outline-none focus:border-indigo-500 focus:bg-white focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
        />
        <button
          type="button"
          onClick={() => void submit()}
          disabled={busy || !question || !answer.trim()}
          className="flex shrink-0 items-center gap-1.5 rounded-xl bg-indigo-600 px-6 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Send className="h-4 w-4" />
          답변
        </button>
      </div>
    </div>
  )
}
