// Pure logic for the live-call screen: state machine, volume -> orb mapping, language choice, timer text,
// error wording. No React, no Agora SDK, so all of it is unit-testable.
import type { AgoraLanguage, AgoraSession } from '@/api/types'

export type CallPhase = 'idle' | 'requesting_mic' | 'starting' | 'connecting' | 'active' | 'ending' | 'ended' | 'error'
export type CallEndReason = 'user' | 'expired' | 'disconnected' | 'agent_left'
export type CallErrorKind = 'mic_denied' | 'mic_missing' | 'mic_busy' | 'not_configured' | 'unsupported_language' | 'server' | 'network' | 'join_failed' | 'unknown'
/** Who is making sound right now (hysteresis-smoothed). */
export type CallActivity = 'quiet' | 'listening' | 'speaking'
/** Mirrors the VoiceOrb states. */
export type CallOrbState = 'idle' | 'listening' | 'processing' | 'speaking' | 'muted'

export interface CallError {
  kind: CallErrorKind
  message: string
}

/** An error with a user-facing kind, thrown by the transport wrapper. */
export class CallFailure extends Error {
  kind: CallErrorKind
  constructor(kind: CallErrorKind, message: string) {
    super(message)
    this.name = 'CallFailure'
    this.kind = kind
  }
}

/* ------------------------------------------------------------------ languages */

/** Pick the call language: the first preferred code the server supports, else English, else the first supported one. */
export function pickCallLanguage(supported: Pick<AgoraLanguage, 'code'>[], preferred: (string | null | undefined)[]): string {
  const has = (c: string) => supported.some((l) => l.code === c)
  for (const p of preferred) {
    const base = p?.toLowerCase().split(/[-_]/)[0]
    if (base && has(base)) return base
  }
  if (has('en')) return 'en'
  return supported[0]?.code ?? 'en'
}

/** Keep only languages the server can speak, in the server's order (guards against a stale/odd status payload). */
export function callLanguages(list: AgoraLanguage[] | undefined | null): AgoraLanguage[] {
  const seen = new Set<string>()
  return (list ?? []).filter((l) => l && l.code && !seen.has(l.code) && (seen.add(l.code), true))
}

/* ------------------------------------------------------------------ timer */

/** 65 -> "1:05", 3725 -> "1:02:05". */
export function formatTimer(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const ss = String(sec).padStart(2, '0')
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`
}

/* ------------------------------------------------------------------ volume -> activity */

// Agora reports levels 0..100. Switch on above the first number, stay on until below the second (stops flicker).
export const SPEAK_ON = 10
export const SPEAK_OFF = 4
export const LISTEN_ON = 14
export const LISTEN_OFF = 6

export function nextActivity(prev: CallActivity, v: { local: number; remote: number; muted: boolean }): CallActivity {
  const remoteHigh = v.remote >= (prev === 'speaking' ? SPEAK_OFF : SPEAK_ON)
  if (remoteHigh) return 'speaking' // the assistant talking wins over background noise on our mic
  if (v.muted) return 'quiet'
  if (v.local >= (prev === 'listening' ? LISTEN_OFF : LISTEN_ON)) return 'listening'
  return 'quiet'
}

export function orbStateFor(s: Pick<CallState, 'phase' | 'muted' | 'activity'>): CallOrbState {
  switch (s.phase) {
    case 'requesting_mic':
    case 'starting':
    case 'connecting':
    case 'ending':
      return 'processing'
    case 'active':
      if (s.activity === 'speaking') return 'speaking'
      if (s.muted) return 'muted'
      return s.activity === 'listening' ? 'listening' : 'idle'
    default:
      return 'idle'
  }
}

/**
 * A stand-in for an AnalyserNode so the existing <Waveform> can show Agora's volume levels:
 * the bars rise and fall with the level. Only the two members Waveform reads are provided.
 */
export function createLevelAnalyser(getLevel: () => number, now: () => number = Date.now): AnalyserNode {
  const bins = 64
  const fake = {
    frequencyBinCount: bins,
    getByteFrequencyData(arr: Uint8Array) {
      const level = Math.min(1, Math.max(0, getLevel() / 100))
      const t = now() / 140
      for (let i = 0; i < arr.length; i++) {
        const wobble = 0.55 + 0.45 * Math.sin(i * 1.7 + t) * Math.cos(i * 0.6 - t * 0.7)
        arr[i] = Math.round(Math.min(1, level * 1.6 * wobble) * 255)
      }
    },
  }
  return fake as unknown as AnalyserNode
}

/* ------------------------------------------------------------------ state machine */

export interface CallState {
  phase: CallPhase
  error: CallError | null
  endReason: CallEndReason | null
  muted: boolean
  activity: CallActivity
  local: number
  remote: number
  session: AgoraSession | null
  /** Survives "Call again" so the next call continues the same conversation. */
  conversationId: string | null
  startedAt: number | null
  elapsed: number
  /** Seconds left before the token ends the call; null until joined. */
  remaining: number | null
  reconnecting: boolean
  notice: string | null
}

export const initialCallState: CallState = {
  phase: 'idle',
  error: null,
  endReason: null,
  muted: false,
  activity: 'quiet',
  local: 0,
  remote: 0,
  session: null,
  conversationId: null,
  startedAt: null,
  elapsed: 0,
  remaining: null,
  reconnecting: false,
  notice: null,
}

export type CallAction =
  | { type: 'begin' }
  | { type: 'mic_ready' }
  | { type: 'session'; session: AgoraSession }
  | { type: 'joined'; now: number }
  | { type: 'volume'; local: number; remote: number }
  | { type: 'muted'; muted: boolean }
  | { type: 'tick'; now: number }
  | { type: 'connection'; reconnecting: boolean }
  | { type: 'notice'; message: string | null }
  | { type: 'ending' }
  | { type: 'ended'; reason: CallEndReason }
  | { type: 'failed'; error: CallError }
  | { type: 'reset' }

/** Phases in which a call is set up or running (the End/Cancel button is shown). */
export const LIVE_PHASES: CallPhase[] = ['requesting_mic', 'starting', 'connecting', 'active', 'ending']
export const isCallLive = (phase: CallPhase) => LIVE_PHASES.includes(phase)

export function callReducer(s: CallState, a: CallAction): CallState {
  switch (a.type) {
    case 'begin':
      return { ...initialCallState, conversationId: s.conversationId, phase: 'requesting_mic' }
    case 'mic_ready':
      return s.phase === 'requesting_mic' ? { ...s, phase: 'starting' } : s
    case 'session':
      return s.phase === 'starting' ? { ...s, phase: 'connecting', session: a.session, conversationId: a.session.conversation_id } : s
    case 'joined':
      return s.phase === 'connecting' && s.session ? { ...s, phase: 'active', startedAt: a.now, elapsed: 0, remaining: s.session.expires_in } : s
    case 'volume': {
      if (s.phase !== 'active') return s
      const activity = nextActivity(s.activity, { local: a.local, remote: a.remote, muted: s.muted })
      return { ...s, local: a.local, remote: a.remote, activity }
    }
    case 'muted':
      return s.phase === 'active' ? { ...s, muted: a.muted, activity: a.muted && s.activity === 'listening' ? 'quiet' : s.activity } : s
    case 'tick': {
      if (s.phase !== 'active' || s.startedAt === null || !s.session) return s
      const elapsed = Math.max(0, Math.floor((a.now - s.startedAt) / 1000))
      return elapsed === s.elapsed ? s : { ...s, elapsed, remaining: Math.max(0, s.session.expires_in - elapsed) }
    }
    case 'connection':
      return s.phase === 'active' ? { ...s, reconnecting: a.reconnecting } : s
    case 'notice':
      return { ...s, notice: a.message }
    case 'ending':
      return s.phase === 'active' || s.phase === 'connecting' || s.phase === 'starting' ? { ...s, phase: 'ending' } : s
    case 'ended':
      if (s.phase === 'ended' || s.phase === 'idle' || s.phase === 'error') return s
      return { ...s, phase: 'ended', endReason: a.reason, activity: 'quiet', local: 0, remote: 0, reconnecting: false, notice: null }
    case 'failed':
      return { ...s, phase: 'error', error: a.error, activity: 'quiet', local: 0, remote: 0, reconnecting: false, notice: null }
    case 'reset':
      return { ...initialCallState, conversationId: s.conversationId }
  }
}

/* ------------------------------------------------------------------ wording */

export const END_REASON_TEXT: Record<CallEndReason, string> = {
  user: 'You ended the call.',
  expired: 'This call reached its time limit. You can call again and pick up where you left off.',
  disconnected: 'The connection was lost. Check your internet and call again.',
  agent_left: 'The assistant left the call. You can start a new call.',
}

/** Wording for an error from the mic (Agora SDK error codes) — also matches browser DOMException names. */
export function classifyMicError(err: unknown): CallError {
  const code = String((err as { code?: unknown })?.code ?? '') + ' ' + String((err as { name?: unknown })?.name ?? '')
  if (/PERMISSION_DENIED|NotAllowedError|SecurityError/i.test(code)) {
    return { kind: 'mic_denied', message: 'Microphone access is blocked. Allow the microphone for this site in your browser settings, then try again.' }
  }
  if (/DEVICE_NOT_FOUND|NotFoundError|OverconstrainedError/i.test(code)) {
    return { kind: 'mic_missing', message: 'No microphone was found. Plug one in or check your device, then try again.' }
  }
  if (/NOT_READABLE|NotReadableError|TrackStartError/i.test(code)) {
    return { kind: 'mic_busy', message: 'Your microphone is being used by another app. Close it and try again.' }
  }
  return { kind: 'unknown', message: 'We could not start your microphone. Check it is connected and allowed, then try again.' }
}

/** Turn anything thrown while starting a call into something calm and actionable. */
export function toCallError(err: unknown): CallError {
  if (err instanceof CallFailure) return { kind: err.kind, message: err.message }
  const e = err as { name?: string; code?: string; status?: number; message?: string }
  if (e?.name === 'ApiError') {
    switch (e.code) {
      case 'agora_not_configured':
      case 'murf_not_configured':
        return { kind: 'not_configured', message: 'Live calls are not set up on this server yet. Add the Agora and Murf keys in backend/.env.' }
      case 'unsupported_language':
        return { kind: 'unsupported_language', message: 'Live calls are not available in that language. Pick another one.' }
      case 'network_error':
        return { kind: 'network', message: e.message || 'Cannot reach the server. Check that the backend is running and try again.' }
      default:
        return { kind: 'server', message: e.message || 'The call could not be started. Please try again.' }
    }
  }
  return { kind: 'unknown', message: e?.message || 'Something went wrong starting the call. Please try again.' }
}
