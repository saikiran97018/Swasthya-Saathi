import { describe, expect, it } from 'vitest'
import type { Message, ServerEvent } from '@/api/types'
import { LIVE_REPLY_ID, SpeechStreamer } from './speechStreamer'

const assistant = (id: string, content: string): ServerEvent => ({
  type: 'message',
  message: { id, conversation_id: 'c', seq: 2, role: 'assistant', content, language: 'en', input_mode: 'text', source: 'ai', tools_used: [], tool_executions: [], pending_confirmation: false, created_at: '2026-11-20T10:00:00Z' } satisfies Message,
})

function setup() {
  const spoken: string[] = []
  const queued: { id: string; blob: Promise<Blob> }[] = []
  const remembered = new Map<string, Promise<Blob>[]>()
  const streamer = new SpeechStreamer({
    synthesize: (text) => {
      spoken.push(text)
      return Promise.resolve(new Blob([text]))
    },
    enqueue: (id, blob) => queued.push({ id, blob }),
    remember: (id, blobs) => remembered.set(id, blobs),
  })
  return { streamer, spoken, queued, remembered }
}

const tokens = (text: string): ServerEvent[] => text.split(/(?<= )/).map((delta) => ({ type: 'token', delta }))

describe('SpeechStreamer', () => {
  it('speaks each finished sentence while the reply is still streaming', () => {
    const { streamer, spoken } = setup()
    const text = 'Fever for two days should be checked by a doctor. Please drink plenty of fluids and rest well. I can book a visit'
    tokens(text).forEach((e) => streamer.handle(e))
    expect(spoken).toEqual(['Fever for two days should be checked by a doctor.', 'Please drink plenty of fluids and rest well.'])
  })

  it('flushes the unfinished tail when the message arrives and remembers audio under the message id', () => {
    const { streamer, spoken, queued, remembered } = setup()
    const text = 'Fever for two days should be checked by a doctor. Shall I book a visit for you today'
    tokens(text).forEach((e) => streamer.handle(e))
    streamer.handle(assistant('a1', text))
    expect(spoken).toEqual(['Fever for two days should be checked by a doctor.', 'Shall I book a visit for you today'])
    expect(queued.every((q) => q.id === LIVE_REPLY_ID)).toBe(true)
    expect(remembered.get('a1')).toHaveLength(2)
  })

  it('speaks the message content when no tokens streamed (fallback / confirmation text)', () => {
    const { streamer, spoken, remembered } = setup()
    streamer.handle(assistant('a1', "I'm ready to do the following: book Dr Rao at 10:00. Please confirm to continue."))
    expect(spoken.length).toBeGreaterThan(0)
    expect(spoken.join(' ')).toContain('Please confirm to continue.')
    expect(remembered.has('a1')).toBe(true)
  })

  it('starts a clean buffer for each assistant message', () => {
    const { streamer, spoken } = setup()
    tokens('Let me check the available slots for you now').forEach((e) => streamer.handle(e))
    streamer.handle(assistant('a1', 'Let me check the available slots for you now'))
    tokens('Dr Rao has a free slot tomorrow at ten in the morning.').forEach((e) => streamer.handle(e))
    streamer.handle(assistant('a2', 'Dr Rao has a free slot tomorrow at ten in the morning.'))
    expect(spoken).toEqual(['Let me check the available slots for you now', 'Dr Rao has a free slot tomorrow at ten in the morning.'])
  })

  it('discards buffered text on error or cancel', () => {
    const { streamer, spoken } = setup()
    tokens('This sentence never finishes').forEach((e) => streamer.handle(e))
    streamer.handle({ type: 'cancelled' })
    streamer.handle(assistant('a1', ''))
    expect(spoken).toEqual([])
  })

  it('never speaks user messages', () => {
    const { streamer, spoken } = setup()
    const m = (assistant('u1', 'I have a fever') as Extract<ServerEvent, { type: 'message' }>).message
    streamer.handle({ type: 'message', message: { ...m, role: 'user' as never } })
    expect(spoken).toEqual([])
  })
})
