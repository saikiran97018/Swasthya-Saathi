// Orchestrates one live call: mic -> create cloud agent -> join channel -> timer/expiry -> clean shutdown.
// Depends only on the small CallTransport interface (see agoraCall.ts for the real Agora implementation),
// so the whole flow is unit-testable with a fake.
import type { AgoraSession, AgoraSessionBody } from '@/api/types'
import { toCallError, type CallAction, type CallEndReason } from './callState'

export interface JoinCredentials {
  appId: string
  channel: string
  token: string
  uid: number
  agentUid: number
}

export interface TransportHandlers {
  /** Levels 0..100 for our mic and for the assistant (every remote user). */
  onVolume: (local: number, remote: number) => void
  onConnection: (state: 'connected' | 'reconnecting' | 'disconnected') => void
  onAgentLeft: () => void
  onNotice: (message: string) => void
}

export interface CallTransport {
  /** Ask for the microphone. Throws a CallFailure (mic_denied / mic_missing / mic_busy). */
  prepareMic(): Promise<void>
  /** Join the channel, publish the mic and play the assistant's audio. Throws a CallFailure('join_failed'). */
  join(creds: JoinCredentials): Promise<void>
  setMuted(muted: boolean): Promise<void>
  /** Idempotent; never throws. */
  leave(): Promise<void>
}

export interface CallApi {
  startSession(body: AgoraSessionBody): Promise<AgoraSession>
  stopSession(agentId: string): Promise<void>
  /** Fire-and-forget version for page unload. */
  stopSessionKeepalive(agentId: string): void
}

export interface CallSessionDeps {
  api: CallApi
  createTransport: (handlers: TransportHandlers) => CallTransport
  now?: () => number
}

/** End the call this long before the token's lifetime, so we hang up cleanly instead of being kicked. */
export const EXPIRY_MARGIN_SECONDS = 5
const NOTICE_MS = 6000

export class CallSession {
  private transport: CallTransport | null = null
  private session: AgoraSession | null = null
  private tickTimer: ReturnType<typeof setInterval> | null = null
  private expiryTimer: ReturnType<typeof setTimeout> | null = null
  private noticeTimer: ReturnType<typeof setTimeout> | null = null
  private stopped = false
  private starting = false
  private active = false
  private ending = false
  private cancelled = false
  private disposed = false
  private muted = false

  constructor(
    private readonly deps: CallSessionDeps,
    private readonly dispatch: (a: CallAction) => void,
  ) {}

  private now() {
    return (this.deps.now ?? Date.now)()
  }

  async start(opts: { language: string; conversationId?: string | null }): Promise<void> {
    if (this.starting || this.active || this.disposed) return
    this.starting = true
    this.cancelled = false
    this.ending = false
    this.stopped = false
    this.session = null
    this.muted = false
    this.dispatch({ type: 'begin' })

    const transport = this.deps.createTransport({
      onVolume: (local, remote) => this.dispatch({ type: 'volume', local, remote }),
      onConnection: (s) => {
        if (s === 'disconnected') void this.end('disconnected')
        else this.dispatch({ type: 'connection', reconnecting: s === 'reconnecting' })
      },
      onAgentLeft: () => void this.end('agent_left'),
      onNotice: (message) => this.showNotice(message),
    })
    this.transport = transport

    try {
      await transport.prepareMic()
      if (this.aborted()) return this.abortStart()
      this.dispatch({ type: 'mic_ready' })

      const body: AgoraSessionBody = { language: opts.language }
      if (opts.conversationId) body.conversation_id = opts.conversationId
      const session = await this.deps.api.startSession(body)
      this.session = session
      if (this.aborted()) return this.abortStart()
      this.dispatch({ type: 'session', session })

      await transport.join({ appId: session.app_id, channel: session.channel, token: session.token, uid: session.uid, agentUid: session.agent_uid })
      if (this.aborted()) return this.abortStart()

      this.active = true
      this.starting = false
      this.dispatch({ type: 'joined', now: this.now() })
      this.tickTimer = setInterval(() => this.dispatch({ type: 'tick', now: this.now() }), 1000)
      const ms = Math.max(1, session.expires_in - EXPIRY_MARGIN_SECONDS) * 1000
      this.expiryTimer = setTimeout(() => void this.end('expired'), ms)
    } catch (err) {
      this.starting = false
      if (this.aborted()) return this.abortStart()
      await this.teardown()
      this.dispatch({ type: 'failed', error: toCallError(err) })
    }
  }

  async setMuted(muted: boolean): Promise<void> {
    if (!this.active || !this.transport) return
    this.muted = muted
    this.dispatch({ type: 'muted', muted })
    try {
      await this.transport.setMuted(muted)
    } catch {
      this.muted = !muted // could not change the track: show the real state
      this.dispatch({ type: 'muted', muted: !muted })
      this.showNotice('Could not change your microphone. Try again.')
    }
  }

  get isMuted() {
    return this.muted
  }

  /** The user's End / Cancel button (also used for expiry, lost connection and the assistant leaving). */
  async end(reason: CallEndReason = 'user'): Promise<void> {
    if (this.ending || this.disposed) return
    if (this.starting && !this.active) {
      this.cancelled = true // the start flow notices at its next step and cleans up
      this.dispatch({ type: 'ending' })
      return
    }
    if (!this.active) return
    this.ending = true
    this.active = false
    this.dispatch({ type: 'ending' })
    await this.teardown()
    this.dispatch({ type: 'ended', reason })
  }

  /** Page is going away: hang up without waiting for anything. */
  dispose(): void {
    if (this.disposed) return
    this.disposed = true
    this.clearTimers()
    if (this.session && !this.stopped) {
      this.stopped = true
      this.deps.api.stopSessionKeepalive(this.session.agent_id)
    }
    const t = this.transport
    this.transport = null
    this.active = false
    this.starting = false
    if (t) void t.leave().catch(() => undefined)
  }

  /* -------------------------------------------------------------- internals */

  private aborted() {
    return this.cancelled || this.disposed
  }

  private async abortStart() {
    this.starting = false
    if (this.disposed) return // dispose() already cleaned up
    await this.teardown()
    this.cancelled = false
    this.dispatch({ type: 'reset' })
  }

  private showNotice(message: string) {
    this.dispatch({ type: 'notice', message })
    if (this.noticeTimer) clearTimeout(this.noticeTimer)
    this.noticeTimer = setTimeout(() => this.dispatch({ type: 'notice', message: null }), NOTICE_MS)
  }

  private clearTimers() {
    if (this.tickTimer) clearInterval(this.tickTimer)
    if (this.expiryTimer) clearTimeout(this.expiryTimer)
    if (this.noticeTimer) clearTimeout(this.noticeTimer)
    this.tickTimer = this.expiryTimer = this.noticeTimer = null
  }

  /** Leave the channel and stop the cloud agent (each at most once); never throws. */
  private async teardown() {
    this.clearTimers()
    const jobs: Promise<unknown>[] = []
    if (this.transport) jobs.push(this.transport.leave().catch(() => undefined))
    if (this.session && !this.stopped) {
      this.stopped = true
      jobs.push(this.deps.api.stopSession(this.session.agent_id).catch(() => undefined))
    }
    await Promise.all(jobs)
    this.transport = null
  }
}
