import type { AcademicField, PersonaId, Report } from '../types'

const STORAGE_KEY = 'profaissor.sessions.v1'
const MAX_SESSIONS = 50

export interface SessionRecord {
  id: string
  completedAt: string // ISO 8601
  field: AcademicField | null
  personaIds: PersonaId[]
  report: Report
  estMinutes: number
}

function readAll(): SessionRecord[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    // Storage disabled (private mode, quota, non-browser env) — treat as empty.
    return []
  }
}

function writeAll(sessions: SessionRecord[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions))
  } catch {
    // Best-effort feature — silently drop if storage isn't writable.
  }
}

/** Save a completed session (newest first), capped at MAX_SESSIONS entries. */
export function saveSession(input: Omit<SessionRecord, 'id' | 'completedAt'>): SessionRecord {
  const record: SessionRecord = {
    ...input,
    id: crypto.randomUUID(),
    completedAt: new Date().toISOString(),
  }
  const sessions = [record, ...readAll()].slice(0, MAX_SESSIONS)
  writeAll(sessions)
  return record
}

export function loadSessions(): SessionRecord[] {
  return readAll()
}

/** Remove a single session by id; no-op if it isn't found. */
export function deleteSession(id: string): void {
  writeAll(readAll().filter((session) => session.id !== id))
}

export function clearSessions(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* ignore */
  }
}
