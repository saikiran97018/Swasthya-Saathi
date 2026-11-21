import { describe, expect, it } from 'vitest'
import type { AgoraSession } from '@/api/types'
import {
  CallFailure,
  callLanguages,
  callReducer,
  classifyMicError,
  createLevelAnalyser,
  formatTimer,
  initialCallState,
  nextActivity,
  orbStateFor,
  pickCallLanguage,
  toCallError,
  type CallAction,
  type CallState,
} from './callState'

const session: AgoraSession = {
  app_id: 'app',
  channel: 'ch',
  token: 't',
  uid: 7,
  agent_uid: 99,
  agent_id: 'agent-1',
  conversation_id: 'conv-1',
  language: 'hi',
  mode: 'tools',
  expires_in: 3600,
  greeting: 'Namaste',
  voice: { vendor: 'murf', voice_id: 'v', locale: 'hi-IN' },
}

const run = (actions: CallAction[], from: CallState = initialCallState) => actions.reduce(callReducer, from)
const active = () => run([{ type: 'begin' }, { type: 'mic_ready' }, { type: 'session', session }, { type: 'joined', now: 1000 }])

describe('pickCallLanguage', () => {
  const sup = [{ code: 'en' }, { code: 'hi' }, { code: 'ta' }]
  it('takes the first preferred language that is supported', () => {
    expect(pickCallLanguage(sup, [null, 'ta', 'hi'])).toBe('ta')
  })
  it('understands region tags', () => {
    expect(pickCallLanguage(sup, ['hi-IN'])).toBe('hi')
  })
  it('falls back to English, then to the first supported language', () => {
    expect(pickCallLanguage(sup, ['te'])).toBe('en')
    expect(pickCallLanguage([{ code: 'hi' }, { code: 'ta' }], ['te'])).toBe('hi')
    expect(pickCallLanguage([], ['te'])).toBe('en')
  })
})

describe('callLanguages', () => {
  it('drops duplicates and tolerates missing data', () => {
    const l = { code: 'en', name: 'English', native_name: 'English', voice: 'x' }
    expect(callLanguages([l, { ...l }])).toHaveLength(1)
    expect(callLanguages(undefined)).toEqual([])
  })
})

describe('formatTimer', () => {
  it('formats minutes and hours', () => {
    expect(formatTimer(0)).toBe('0:00')
    expect(formatTimer(65)).toBe('1:05')
    expect(formatTimer(599.9)).toBe('9:59')
    expect(formatTimer(3600)).toBe('1:00:00')
    expect(formatTimer(3725)).toBe('1:02:05')
    expect(formatTimer(-4)).toBe('0:00')
  })
})

describe('nextActivity (volume -> who is talking)', () => {
  it('assistant speech wins over our mic', () => {
    expect(nextActivity('quiet', { local: 60, remote: 30, muted: false })).toBe('speaking')
  })
  it('our voice shows as listening, but not when muted', () => {
    expect(nextActivity('quiet', { local: 40, remote: 0, muted: false })).toBe('listening')
    expect(nextActivity('quiet', { local: 40, remote: 0, muted: true })).toBe('quiet')
  })
  it('has hysteresis so levels near the threshold do not flicker', () => {
    expect(nextActivity('quiet', { local: 0, remote: 7, muted: false })).toBe('quiet')
    expect(nextActivity('speaking', { local: 0, remote: 7, muted: false })).toBe('speaking')
    expect(nextActivity('speaking', { local: 0, remote: 2, muted: false })).toBe('quiet')
    expect(nextActivity('quiet', { local: 9, remote: 0, muted: false })).toBe('quiet')
    expect(nextActivity('listening', { local: 9, remote: 0, muted: false })).toBe('listening')
  })
})

describe('orbStateFor', () => {
  it('shows processing while connecting and idle between calls', () => {
    expect(orbStateFor({ phase: 'connecting', muted: false, activity: 'quiet' })).toBe('processing')
    expect(orbStateFor({ phase: 'idle', muted: false, activity: 'quiet' })).toBe('idle')
    expect(orbStateFor({ phase: 'ended', muted: false, activity: 'quiet' })).toBe('idle')
  })
  it('maps activity in a live call; the assistant speaking beats muted', () => {
    expect(orbStateFor({ phase: 'active', muted: false, activity: 'listening' })).toBe('listening')
    expect(orbStateFor({ phase: 'active', muted: false, activity: 'speaking' })).toBe('speaking')
    expect(orbStateFor({ phase: 'active', muted: true, activity: 'quiet' })).toBe('muted')
    expect(orbStateFor({ phase: 'active', muted: true, activity: 'speaking' })).toBe('speaking')
    expect(orbStateFor({ phase: 'active', muted: false, activity: 'quiet' })).toBe('idle')
  })
})

describe('callReducer', () => {
  it('walks the happy path and starts the timer', () => {
    const s = active()
    expect(s.phase).toBe('active')
    expect(s.conversationId).toBe('conv-1')
    expect(s.remaining).toBe(3600)
    const t = callReducer(s, { type: 'tick', now: 66_000 })
    expect(t.elapsed).toBe(65)
    expect(t.remaining).toBe(3535)
  })

  it('ignores volume and ticks outside an active call', () => {
    const s = run([{ type: 'begin' }])
    expect(callReducer(s, { type: 'volume', local: 90, remote: 90 })).toBe(s)
    expect(callReducer(s, { type: 'tick', now: 5000 })).toBe(s)
  })

  it('drives the orb from volume events and clears mute-listening', () => {
    let s = callReducer(active(), { type: 'volume', local: 50, remote: 0 })
    expect(orbStateFor(s)).toBe('listening')
    s = callReducer(s, { type: 'muted', muted: true })
    expect(s.activity).toBe('quiet')
    s = callReducer(s, { type: 'volume', local: 50, remote: 40 })
    expect(orbStateFor(s)).toBe('speaking')
  })

  it('ends with a reason and resets levels', () => {
    let s = callReducer(active(), { type: 'volume', local: 50, remote: 0 })
    s = run([{ type: 'ending' }, { type: 'ended', reason: 'expired' }], s)
    expect(s).toMatchObject({ phase: 'ended', endReason: 'expired', local: 0, activity: 'quiet' })
    // a late duplicate "ended" (e.g. a disconnect event after hang-up) is ignored
    expect(callReducer(s, { type: 'ended', reason: 'disconnected' }).endReason).toBe('expired')
  })

  it('records a start failure and keeps the conversation id for "try again"', () => {
    const s = run([{ type: 'begin' }, { type: 'mic_ready' }, { type: 'session', session }, { type: 'failed', error: { kind: 'join_failed', message: 'x' } }])
    expect(s.phase).toBe('error')
    expect(s.error?.kind).toBe('join_failed')
    expect(callReducer(s, { type: 'begin' })).toMatchObject({ phase: 'requesting_mic', error: null, conversationId: 'conv-1' })
  })

  it('reset returns to idle but remembers the conversation', () => {
    expect(callReducer(active(), { type: 'reset' })).toMatchObject({ phase: 'idle', conversationId: 'conv-1', session: null })
  })
})

describe('error wording', () => {
  it('classifies microphone errors from Agora and the browser', () => {
    expect(classifyMicError({ code: 'PERMISSION_DENIED' }).kind).toBe('mic_denied')
    expect(classifyMicError({ name: 'NotAllowedError' }).kind).toBe('mic_denied')
    expect(classifyMicError({ code: 'DEVICE_NOT_FOUND' }).kind).toBe('mic_missing')
    expect(classifyMicError({ code: 'NOT_READABLE' }).kind).toBe('mic_busy')
    expect(classifyMicError(new Error('???')).kind).toBe('unknown')
  })

  it('maps API errors and transport failures', () => {
    expect(toCallError(new CallFailure('join_failed', 'nope'))).toEqual({ kind: 'join_failed', message: 'nope' })
    expect(toCallError({ name: 'ApiError', code: 'agora_not_configured', message: 'm' }).kind).toBe('not_configured')
    expect(toCallError({ name: 'ApiError', code: 'murf_not_configured', message: 'm' }).kind).toBe('not_configured')
    expect(toCallError({ name: 'ApiError', code: 'unsupported_language', message: 'm' }).kind).toBe('unsupported_language')
    expect(toCallError({ name: 'ApiError', code: 'agora_error', message: 'Agora said no' })).toEqual({ kind: 'server', message: 'Agora said no' })
    expect(toCallError({ name: 'ApiError', code: 'network_error', status: 0, message: 'offline' }).kind).toBe('network')
  })
})

describe('createLevelAnalyser', () => {
  it('fills bars in proportion to the level', () => {
    let level = 0
    const a = createLevelAnalyser(() => level, () => 1000)
    const bars = new Uint8Array(a.frequencyBinCount)
    a.getByteFrequencyData(bars)
    expect(Math.max(...bars)).toBe(0)
    level = 80
    a.getByteFrequencyData(bars)
    expect(Math.max(...bars)).toBeGreaterThan(100)
  })
})
