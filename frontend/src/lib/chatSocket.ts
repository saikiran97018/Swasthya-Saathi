import { bootstrapGuest, ensureToken, wsUrl } from '@/api/client'
import type { ChatOut, ClientCommand, ServerEvent } from '@/api/types'

export type ConnectionStatus = 'connecting' | 'open' | 'reconnecting' | 'closed'

interface Handlers {
  onEvent: (ev: ServerEvent) => void
  onStatus: (status: ConnectionStatus) => void
}

const PING_MS = 25_000
const BACKOFF = [800, 1600, 3200, 6400, 10_000]

/**
 * WebSocket client for /api/v1/ws/chat: connects with the guest JWT, answers with automatic
 * reconnect + exponential backoff, and keeps the connection warm with a ping every 25 s.
 * `send` returns false when the socket isn't open so the caller can fall back to REST.
 */
export class ChatSocket {
  private ws: WebSocket | null = null
  private pingTimer: ReturnType<typeof setInterval> | null = null
  private retryTimer: ReturnType<typeof setTimeout> | null = null
  private attempt = 0
  private stopped = false
  private status: ConnectionStatus = 'closed'

  constructor(private readonly h: Handlers) {}

  get connection() {
    return this.status
  }

  start() {
    this.stopped = false
    void this.connect()
  }

  stop() {
    this.stopped = true
    this.clearTimers()
    this.ws?.close()
    this.ws = null
    this.setStatus('closed')
  }

  send(cmd: ClientCommand): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false
    try {
      this.ws.send(JSON.stringify(cmd))
      return true
    } catch {
      return false
    }
  }

  private setStatus(s: ConnectionStatus) {
    if (this.status === s) return
    this.status = s
    this.h.onStatus(s)
  }

  private clearTimers() {
    if (this.pingTimer) clearInterval(this.pingTimer)
    if (this.retryTimer) clearTimeout(this.retryTimer)
    this.pingTimer = this.retryTimer = null
  }

  private async connect() {
    if (this.stopped) return
    this.setStatus(this.attempt === 0 ? 'connecting' : 'reconnecting')
    let token: string
    try {
      token = await ensureToken()
    } catch {
      return this.scheduleRetry()
    }
    if (this.stopped) return

    const ws = new WebSocket(wsUrl(token))
    this.ws = ws
    ws.onopen = () => {
      this.attempt = 0
      this.setStatus('open')
      this.pingTimer = setInterval(() => this.send({ type: 'ping' }), PING_MS)
    }
    ws.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data as string) as ServerEvent
        if (ev.type !== 'pong') this.h.onEvent(ev)
      } catch {
        /* ignore malformed frame */
      }
    }
    ws.onclose = (e) => {
      this.clearTimers()
      if (this.ws === ws) this.ws = null
      if (this.stopped) return
      // 4401 = the backend rejected our token: get a new guest token on the next attempt.
      if (e.code === 4401) void bootstrapGuest().catch(() => undefined)
      this.scheduleRetry()
    }
    ws.onerror = () => ws.close()
  }

  private scheduleRetry() {
    if (this.stopped) return
    this.setStatus('reconnecting')
    const delay = BACKOFF[Math.min(this.attempt, BACKOFF.length - 1)] ?? 10_000
    this.attempt += 1
    this.retryTimer = setTimeout(() => void this.connect(), delay)
  }
}

/** Turn a REST /chat (or confirm) reply into the same events the WebSocket would have produced. */
export function chatOutToEvents(out: ChatOut): ServerEvent[] {
  const events: ServerEvent[] = [{ type: 'conversation', conversation: out.conversation }, { type: 'language', language: out.language, changed: false }]
  if (out.user_message) events.push({ type: 'user_message', message: out.user_message })
  for (const message of out.messages) events.push({ type: 'message', message })
  // Latest state of every tool run in the turn. After a confirm call this carries the confirmed action's
  // outcome, which no message in `messages` repeats, so the existing tool card gets updated by it.
  for (const tool_execution of out.tool_executions ?? []) events.push({ type: 'tool_result', tool_execution })
  if (out.pending_confirmation) events.push({ type: 'confirmation_required', tool_execution: out.pending_confirmation })
  events.push({ type: 'done', execution_id: out.execution_id ?? '', status: out.pending_confirmation ? 'awaiting_confirmation' : 'completed', language: out.language })
  return events
}
