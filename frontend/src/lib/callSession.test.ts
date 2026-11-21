import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AgoraSession } from '@/api/types'
import { CallSession, EXPIRY_MARGIN_SECONDS, type CallApi, type CallTransport, type TransportHandlers } from './callSession'
import { CallFailure, callReducer, initialCallState, type CallAction, type CallState } from './callState'

const session: AgoraSession = {
  app_id: 'app',
  channel: 'ch',
  token: 'tok',
  uid: 7,
  agent_uid: 99,
  agent_id: 'agent-1',
  conversation_id: 'conv-1',
  language: 'hi',
  mode: 'tools',
  expires_in: 60,
  greeting: 'Namaste',
  voice: { vendor: 'murf', voice_id: 'v', locale: 'hi-IN' },
}

const apiError = (code: string, message: string) => Object.assign(new Error(message), { name: 'ApiError', code })

function setup(over: { transport?: Partial<CallTransport>; api?: Partial<CallApi> } = {}) {
  let handlers!: TransportHandlers
  const transport: CallTransport = {
    prepareMic: vi.fn(async () => undefined),
    join: vi.fn(async () => undefined),
    setMuted: vi.fn(async () => undefined),
    leave: vi.fn(async () => undefined),
    ...over.transport,
  }
  const api: CallApi = {
    startSession: vi.fn(async () => session),
    stopSession: vi.fn(async () => undefined),
    stopSessionKeepalive: vi.fn(),
    ...over.api,
  }
  let state: CallState = initialCallState
  const actions: CallAction[] = []
  const call = new CallSession(
    {
      api,
      createTransport: (h) => {
        handlers = h
        return transport
      },
    },
    (a) => {
      actions.push(a)
      state = callReducer(state, a)
    },
  )
  return {
    call,
    transport,
    api,
    actions,
    get state() {
      return state
    },
    get handlers() {
      return handlers
    },
  }
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('CallSession', () => {
  it('asks for the mic first, then creates the agent, then joins with the returned credentials', async () => {
    const t = setup()
    await t.call.start({ language: 'hi', conversationId: 'conv-0' })
    expect(t.api.startSession).toHaveBeenCalledWith({ language: 'hi', conversation_id: 'conv-0' })
    expect(t.transport.join).toHaveBeenCalledWith({ appId: 'app', channel: 'ch', token: 'tok', uid: 7, agentUid: 99 })
    expect(t.state.phase).toBe('active')
    const mic = (t.transport.prepareMic as ReturnType<typeof vi.fn>).mock.invocationCallOrder[0]!
    const create = (t.api.startSession as ReturnType<typeof vi.fn>).mock.invocationCallOrder[0]!
    expect(mic).toBeLessThan(create)
  })

  it('does not call the server when the mic is denied', async () => {
    const t = setup({
      transport: {
        prepareMic: vi.fn(async () => {
          throw new CallFailure('mic_denied', 'blocked')
        }),
      },
    })
    await t.call.start({ language: 'en' })
    expect(t.api.startSession).not.toHaveBeenCalled()
    expect(t.state.phase).toBe('error')
    expect(t.state.error).toEqual({ kind: 'mic_denied', message: 'blocked' })
  })

  it('stops the cloud agent and reports the error when joining fails', async () => {
    const t = setup({
      transport: {
        join: vi.fn(async () => {
          throw new CallFailure('join_failed', 'no join')
        }),
      },
    })
    await t.call.start({ language: 'en' })
    expect(t.state.phase).toBe('error')
    expect(t.state.error?.kind).toBe('join_failed')
    expect(t.api.stopSession).toHaveBeenCalledWith('agent-1')
    expect(t.transport.leave).toHaveBeenCalled()
  })

  it('maps a backend failure to a friendly error and closes the mic', async () => {
    const t = setup({
      api: {
        startSession: vi.fn(async () => {
          throw apiError('murf_not_configured', 'Murf missing')
        }),
      },
    })
    await t.call.start({ language: 'en' })
    expect(t.state.error?.kind).toBe('not_configured')
    expect(t.transport.leave).toHaveBeenCalled()
    expect(t.api.stopSession).not.toHaveBeenCalled() // there is no agent to stop
  })

  it('ticks the timer once a second and mutes through the transport', async () => {
    const t = setup()
    await t.call.start({ language: 'en' })
    await vi.advanceTimersByTimeAsync(3000)
    expect(t.state.elapsed).toBe(3)
    await t.call.setMuted(true)
    expect(t.transport.setMuted).toHaveBeenCalledWith(true)
    expect(t.state.muted).toBe(true)
  })

  it('reverts the mute toggle if the track cannot change', async () => {
    const t = setup({
      transport: {
        setMuted: vi.fn(async () => {
          throw new Error('x')
        }),
      },
    })
    await t.call.start({ language: 'en' })
    await t.call.setMuted(true)
    expect(t.state.muted).toBe(false)
    expect(t.state.notice).toBeTruthy()
  })

  it('hangs up cleanly on End: leaves, stops the agent once, reports "user"', async () => {
    const t = setup()
    await t.call.start({ language: 'en' })
    await t.call.end()
    await t.call.end() // a second click is a no-op
    expect(t.transport.leave).toHaveBeenCalledTimes(1)
    expect(t.api.stopSession).toHaveBeenCalledTimes(1)
    expect(t.state).toMatchObject({ phase: 'ended', endReason: 'user' })
  })

  it('ends the call just before the token expires', async () => {
    const t = setup()
    await t.call.start({ language: 'en' })
    await vi.advanceTimersByTimeAsync((session.expires_in - EXPIRY_MARGIN_SECONDS) * 1000 - 1)
    expect(t.state.phase).toBe('active')
    await vi.advanceTimersByTimeAsync(2)
    expect(t.state).toMatchObject({ phase: 'ended', endReason: 'expired' })
    expect(t.api.stopSession).toHaveBeenCalledWith('agent-1')
  })

  it('ends when the connection is lost or the assistant leaves, and tolerates a reconnect blip', async () => {
    const a = setup()
    await a.call.start({ language: 'en' })
    a.handlers.onConnection('reconnecting')
    expect(a.state.reconnecting).toBe(true)
    a.handlers.onConnection('connected')
    expect(a.state.reconnecting).toBe(false)
    a.handlers.onConnection('disconnected')
    await vi.advanceTimersByTimeAsync(0)
    expect(a.state).toMatchObject({ phase: 'ended', endReason: 'disconnected' })

    const b = setup()
    await b.call.start({ language: 'en' })
    b.handlers.onAgentLeft()
    await vi.advanceTimersByTimeAsync(0)
    expect(b.state.endReason).toBe('agent_left')
  })

  it('feeds volume events into the state', async () => {
    const t = setup()
    await t.call.start({ language: 'en' })
    t.handlers.onVolume(0, 40)
    expect(t.state.activity).toBe('speaking')
  })

  it('cancelling while connecting cleans up and returns to idle', async () => {
    let release!: () => void
    const t = setup({ transport: { join: vi.fn(() => new Promise<void>((r) => (release = r))) } })
    const started = t.call.start({ language: 'en' })
    await vi.advanceTimersByTimeAsync(0)
    expect(t.state.phase).toBe('connecting')
    await t.call.end()
    release()
    await started
    expect(t.state.phase).toBe('idle')
    expect(t.api.stopSession).toHaveBeenCalledWith('agent-1')
    expect(t.transport.leave).toHaveBeenCalled()
  })

  it('dispose (unmount / pagehide) fires the keepalive stop and leaves, once', async () => {
    const t = setup()
    await t.call.start({ language: 'en' })
    t.call.dispose()
    t.call.dispose()
    expect(t.api.stopSessionKeepalive).toHaveBeenCalledTimes(1)
    expect(t.api.stopSessionKeepalive).toHaveBeenCalledWith('agent-1')
    expect(t.transport.leave).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(5000)
    expect(t.api.stopSession).not.toHaveBeenCalled()
  })
})
