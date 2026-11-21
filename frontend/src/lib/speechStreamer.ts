import type { ServerEvent } from '@/api/types'
import { extractSentences } from './sentences'

/**
 * Speaks a reply sentence-by-sentence while it is still streaming.
 *
 *  - `token` events fill a buffer; every finished sentence is synthesized right away and queued.
 *  - A `message` event flushes whatever is left (and, if no tokens arrived for it, e.g. a fallback
 *    or confirmation text, speaks the message content instead).
 *  - Once the message id is known, its audio is remembered so "Replay" never re-requests it.
 */
export interface StreamerDeps {
  /** Synthesize one piece of text into a WAV blob. */
  synthesize: (text: string) => Promise<Blob>
  /** Queue audio for playback. */
  enqueue: (messageId: string, blob: Promise<Blob>) => void
  /** Remember all audio of a finished message. */
  remember: (messageId: string, blobs: Promise<Blob>[]) => void
  /** Called whenever speech is skipped because the language has no voice. */
  onUnavailable?: () => void
}

/** Queue id used while a reply is being spoken live (before its message id is known). */
export const LIVE_REPLY_ID = 'live-reply'

export class SpeechStreamer {
  private buffer = ''
  private pending: Promise<Blob>[] = []
  private sawTokens = false

  constructor(private deps: StreamerDeps) {}

  /** Cancel in-progress buffering (user interrupted or a new turn started). */
  reset() {
    this.buffer = ''
    this.pending = []
    this.sawTokens = false
  }

  handle(ev: ServerEvent) {
    if (ev.type === 'token') {
      this.sawTokens = true
      this.buffer += ev.delta
      const { sentences, rest } = extractSentences(this.buffer, false)
      this.buffer = rest
      sentences.forEach((s) => this.speak(s))
    } else if (ev.type === 'message' && ev.message.role === 'assistant') {
      if (this.sawTokens) {
        const { sentences } = extractSentences(this.buffer, true)
        sentences.forEach((s) => this.speak(s))
      } else if (ev.message.content.trim()) {
        extractSentences(ev.message.content, true).sentences.forEach((s) => this.speak(s))
      }
      if (this.pending.length) this.deps.remember(ev.message.id, this.pending)
      this.reset()
    } else if (ev.type === 'error' || ev.type === 'cancelled') {
      this.reset()
    }
  }

  private speak(text: string) {
    const blob = this.deps.synthesize(text)
    this.pending.push(blob)
    this.deps.enqueue(LIVE_REPLY_ID, blob)
  }
}
