import { useEffect, useRef, useState } from 'react'
import { evaluateAnswer, fetchQuestion } from '../api'
import { useSpeechRecognition } from '../hooks/useSpeechRecognition'
import { getPersona } from '../personas'
import type { ChatMessage, PersonaId, Slide, TranscriptTurn } from '../types'

interface Props {
  script: string
  slides: Slide[]
  personaIds: PersonaId[]
  onFinish: (transcript: TranscriptTurn[]) => void
}

export default function SparScreen({ script, slides, personaIds, onFinish }: Props) {
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
      setAnswer((prev) => (prev.trim() ? prev.trimEnd() + ' ' : '') + text)
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
      const q = await fetchQuestion(script, slides, pid)
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
      })
      pushMessage({
        role: 'verdict',
        personaId: pid,
        text: `평가: ${ev.verdict}\n👍 ${ev.strengths}\n⚠️ ${ev.gaps}`,
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
    <div className="mx-auto flex h-screen max-w-3xl flex-col px-4 py-6">
      {/* header */}
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-3xl">{persona.emoji}</span>
          <div>
            <div className="font-semibold">{persona.name}</div>
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
                  ? 'bg-indigo-500'
                  : i === personaIndex
                    ? 'bg-indigo-400 animate-pulse'
                    : 'bg-slate-700')
              }
              title={getPersona(id).name}
            />
          ))}
          <span className="ml-2 text-xs text-slate-400">
            {personaIndex + 1} / {personaIds.length}
          </span>
        </div>
      </div>

      {/* chat log */}
      <div
        ref={scrollRef}
        className="flex-1 space-y-4 overflow-y-auto rounded-2xl border border-slate-800 bg-slate-900/40 p-4"
      >
        {messages.map((m, i) => {
          const p = getPersona(m.personaId)
          if (m.role === 'answer') {
            return (
              <div key={i} className="flex justify-end">
                <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-tr-sm bg-indigo-600 px-4 py-2 text-sm">
                  {m.text}
                </div>
              </div>
            )
          }
          if (m.role === 'verdict') {
            return (
              <div key={i} className="flex justify-center">
                <div className="w-full max-w-[90%] whitespace-pre-wrap rounded-xl border border-slate-700 bg-slate-800/60 px-4 py-2 text-xs text-slate-300">
                  {m.text}
                </div>
              </div>
            )
          }
          return (
            <div key={i} className="flex justify-start">
              <div className="max-w-[80%] rounded-2xl rounded-tl-sm border border-slate-700 bg-slate-800 px-4 py-2 text-sm">
                <div className="mb-1 text-xs font-semibold text-indigo-300">
                  {p.emoji} {p.name}
                </div>
                <span className="whitespace-pre-wrap">{m.text}</span>
              </div>
            </div>
          )
        })}
        {busy && (
          <div className="flex justify-start">
            <div className="rounded-2xl border border-slate-700 bg-slate-800 px-4 py-2 text-sm text-slate-400">
              생각 중…
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="mt-3 rounded-lg border border-rose-700 bg-rose-950/40 px-4 py-2 text-sm text-rose-300">
          오류: {error}
        </div>
      )}

      {/* live dictation preview */}
      {listening && (
        <div className="mt-3 flex items-center gap-2 text-xs text-indigo-300">
          <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-rose-500" />
          받아쓰는 중… <span className="text-slate-400">{interim || '(말해보세요)'}</span>
        </div>
      )}

      {/* answer input */}
      <div className="mt-4 flex gap-2">
        {sttSupported && (
          <button
            type="button"
            data-testid="mic-btn"
            onClick={toggleMic}
            disabled={busy || !question}
            title={listening ? '받아쓰기 중지' : '음성으로 답변 (STT)'}
            className={
              'flex h-auto w-12 shrink-0 items-center justify-center rounded-xl border text-xl transition disabled:cursor-not-allowed disabled:opacity-40 ' +
              (listening
                ? 'border-rose-500 bg-rose-500/20 text-rose-300 animate-pulse'
                : 'border-slate-700 bg-slate-800/60 text-slate-300 hover:border-indigo-500 hover:text-indigo-300')
            }
          >
            {listening ? '⏹' : '🎙'}
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
              ? '답변을 입력하거나 🎙 버튼으로 말하세요… (Ctrl/⌘ + Enter 로 전송)'
              : '답변을 입력하세요… (Ctrl/⌘ + Enter 로 전송)'
          }
          className="flex-1 resize-none rounded-xl border border-slate-700 bg-slate-800/60 px-4 py-3 text-sm outline-none focus:border-indigo-500 disabled:opacity-50"
        />
        <button
          type="button"
          onClick={() => void submit()}
          disabled={busy || !question || !answer.trim()}
          className="shrink-0 rounded-xl bg-indigo-600 px-6 font-semibold transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          답변
        </button>
      </div>
    </div>
  )
}
