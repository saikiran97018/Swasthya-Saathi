import { describe, expect, it } from 'vitest'
import type { Conversation, ConversationDetail, Message, ServerEvent, ToolExecution } from '@/api/types'
import { chatOutToEvents } from './chatSocket'
import { chatReducer, initialChatState, isTempId, lastUserMessage, pendingConfirmation, type ChatAction, type ChatState } from './chatReducer'

const CID = 'conv-1'
const NOW = '2026-11-20T10:00:00Z'

const conversation = (over: Partial<Conversation> = {}): Conversation => ({
  id: CID, title: 'Fever', language: 'en', created_at: NOW, updated_at: NOW, last_message_at: NOW, message_count: 0, voice_message_count: 0, summary: null, ...over,
})

const msg = (over: Partial<Message> & Pick<Message, 'id' | 'seq' | 'role'>): Message => ({
  conversation_id: CID, content: '', language: 'en', input_mode: 'text', source: over.role === 'user' ? 'user' : 'ai', tools_used: [], tool_executions: [], pending_confirmation: false, created_at: NOW, ...over,
})

const tool = (over: Partial<ToolExecution> = {}): ToolExecution => ({
  id: 'tool-1', execution_id: 'run-1', conversation_id: CID, assistant_message_id: 'a1', tool_name: 'book_appointment', arguments: { slot: '10:00' }, result: null,
  summary: null, explanation: 'Book 10:00 with Dr Rao', status: 'running', requires_confirmation: false, duration_ms: null, error: null, created_at: NOW, ...over,
})

const run = (events: ServerEvent[], start: ChatState = initialChatState): ChatState =>
  events.reduce((s, event) => chatReducer(s, { type: 'event', event } as ChatAction), start)

const send = (s: ChatState, text = 'I have a fever', tempId = 'tmp-1'): ChatState => chatReducer(s, { type: 'send', text, inputMode: 'text', tempId, now: NOW })

describe('sending and streaming', () => {
  it('shows an optimistic user bubble and enters the running state', () => {
    const s = send(initialChatState)
    expect(s.status).toBe('running')
    expect(s.messages).toHaveLength(1)
    expect(s.messages[0]).toMatchObject({ role: 'user', content: 'I have a fever', localStatus: 'sending' })
    expect(isTempId(s.messages[0]!.id)).toBe(true)
  })

  it('replaces the optimistic bubble with the real message, builds the stream, then swaps in the final message', () => {
    let s = send(initialChatState)
    s = run([
      { type: 'conversation', conversation: conversation() },
      { type: 'language', language: 'en', changed: false },
      { type: 'user_message', message: msg({ id: 'u1', seq: 1, role: 'user', content: 'I have a fever' }) },
      { type: 'stage', stage: 'thinking' },
    ], s)
    expect(s.conversationId).toBe(CID)
    expect(s.messages.map((m) => m.id)).toEqual(['u1'])
    expect(s.messages[0]!.localStatus).toBeUndefined()

    s = run([{ type: 'token', delta: 'Please ' }, { type: 'token', delta: 'rest.' }], s)
    expect(s.streamingText).toBe('Please rest.')
    expect(s.stage).toBe('responding')

    s = run([
      { type: 'message', message: msg({ id: 'a1', seq: 2, role: 'assistant', content: 'Please rest.' }) },
      { type: 'done', execution_id: 'run-1', status: 'completed' },
    ], s)
    expect(s.streamingText).toBe('')
    expect(s.messages.map((m) => m.content)).toEqual(['I have a fever', 'Please rest.'])
    expect(s).toMatchObject({ status: 'idle', stage: null, executionId: 'run-1' })
  })

  it('upserts a message by id rather than duplicating it', () => {
    let s = run([{ type: 'message', message: msg({ id: 'a1', seq: 2, role: 'assistant', content: 'Checking.' }) }])
    s = run([{ type: 'message', message: msg({ id: 'a1', seq: 2, role: 'assistant', content: 'Checking.', tools_used: ['x'] }) }], s)
    expect(s.messages).toHaveLength(1)
    expect(s.messages[0]!.tools_used).toEqual(['x'])
  })

  it('keeps messages ordered by seq even if events arrive out of order', () => {
    const s = run([
      { type: 'message', message: msg({ id: 'a2', seq: 4, role: 'assistant', content: 'later' }) },
      { type: 'message', message: msg({ id: 'a1', seq: 2, role: 'assistant', content: 'earlier' }) },
    ])
    expect(s.messages.map((m) => m.id)).toEqual(['a1', 'a2'])
  })

  it('clears the live bubble for each assistant message, so tool-step text does not leak into the next answer', () => {
    const s = run([
      { type: 'token', delta: 'Let me check.' },
      { type: 'message', message: msg({ id: 'a1', seq: 2, role: 'assistant', content: 'Let me check.' }) },
      { type: 'token', delta: 'Here you go.' },
    ])
    expect(s.streamingText).toBe('Here you go.')
  })
})

describe('tool events', () => {
  const base = () => run([{ type: 'message', message: msg({ id: 'a1', seq: 2, role: 'assistant', content: 'Checking availability.' }) }])

  it('merges tool_start then tool_result into the owning assistant message', () => {
    let s = run([{ type: 'tool_start', tool_execution: tool() }], base())
    expect(s.messages[0]!.tool_executions).toEqual([expect.objectContaining({ id: 'tool-1', status: 'running' })])
    expect(s.stage).toBe('tool')
    s = run([{ type: 'tool_result', tool_execution: tool({ status: 'success', summary: 'Slot free', duration_ms: 120 }) }], s)
    expect(s.messages[0]!.tool_executions).toHaveLength(1)
    expect(s.messages[0]!.tool_executions[0]).toMatchObject({ status: 'success', summary: 'Slot free', duration_ms: 120 })
  })

  it('a later message event for the same id carries the final tool list', () => {
    let s = run([{ type: 'tool_start', tool_execution: tool() }], base())
    s = run([{ type: 'message', message: msg({ id: 'a1', seq: 2, role: 'assistant', content: 'Checking availability.', tool_executions: [tool({ status: 'success' })] }) }], s)
    expect(s.messages[0]!.tool_executions[0]!.status).toBe('success')
  })

  it('ignores a tool event whose message is unknown or has no assistant_message_id', () => {
    const s = base()
    expect(run([{ type: 'tool_start', tool_execution: tool({ assistant_message_id: null }) }], s).messages[0]!.tool_executions).toHaveLength(0)
    expect(run([{ type: 'tool_start', tool_execution: tool({ assistant_message_id: 'nope' }) }], s).messages[0]!.tool_executions).toHaveLength(0)
  })
})

describe('confirmation flow', () => {
  const awaiting = () =>
    run([
      { type: 'message', message: msg({ id: 'a1', seq: 2, role: 'assistant', content: 'I will book Dr Rao at 10:00.' }) },
      { type: 'confirmation_required', tool_execution: tool({ status: 'awaiting_confirmation', requires_confirmation: true }) },
      { type: 'done', execution_id: 'run-1', status: 'awaiting_confirmation' },
    ])

  it('exposes the pending tool call and waits', () => {
    const s = awaiting()
    expect(s.status).toBe('awaiting_confirmation')
    expect(s.messages[0]!.pending_confirmation).toBe(true)
    expect(pendingConfirmation(s)?.id).toBe('tool-1')
  })

  it('confirm marks the tool running and the turn running; the result clears the pending state', () => {
    let s = chatReducer(awaiting(), { type: 'confirm', executionId: 'tool-1' })
    expect(s.status).toBe('running')
    expect(pendingConfirmation(s)).toBeNull()
    expect(s.messages[0]!.tool_executions[0]!.status).toBe('running')
    s = run([
      { type: 'tool_result', tool_execution: tool({ status: 'success', summary: 'Booked' }) },
      { type: 'message', message: msg({ id: 'a2', seq: 4, role: 'assistant', content: 'Done, you are booked.', tools_used: ['book_appointment'], source: 'tool' }) },
      { type: 'done', execution_id: 'run-1', status: 'completed' },
    ], s)
    expect(s.status).toBe('idle')
    expect(s.messages.at(-1)).toMatchObject({ source: 'tool', content: 'Done, you are booked.' })
  })

  it('sending a new message cancels the unanswered confirmation locally (backend does the same)', () => {
    const s = send(awaiting(), 'never mind')
    expect(pendingConfirmation(s)).toBeNull()
    expect(s.messages[0]!.tool_executions[0]!.status).toBe('cancelled')
    expect(s.messages[0]!.pending_confirmation).toBe(false)
  })

  it('a reloaded conversation with a pending confirmation resumes in the awaiting state', () => {
    const detail: ConversationDetail = {
      ...conversation(),
      messages: [msg({ id: 'u1', seq: 1, role: 'user', content: 'book it' }), msg({ id: 'a1', seq: 2, role: 'assistant', content: 'Confirm?', pending_confirmation: true, tool_executions: [tool({ status: 'awaiting_confirmation' })] })],
    }
    const s = chatReducer(initialChatState, { type: 'load', detail })
    expect(s.status).toBe('awaiting_confirmation')
    expect(pendingConfirmation(s)?.id).toBe('tool-1')
    expect(s.conversation).not.toHaveProperty('messages')
  })
})

describe('errors, cancel and regenerate', () => {
  it('an error ends the turn, marks the unsent message failed, and keeps the message for retry', () => {
    let s = send(initialChatState)
    s = run([{ type: 'error', code: 'llm_not_configured', message: 'The language model is not configured.', retryable: false }], s)
    expect(s.status).toBe('idle')
    expect(s.error).toEqual({ code: 'llm_not_configured', message: 'The language model is not configured.', retryable: false })
    expect(s.messages[0]!.localStatus).toBe('failed')
  })

  it('an error after the server stored the message leaves it as a normal message', () => {
    let s = send(initialChatState)
    s = run([{ type: 'user_message', message: msg({ id: 'u1', seq: 1, role: 'user', content: 'I have a fever' }) }, { type: 'token', delta: 'par' }, { type: 'error', code: 'llm_timeout', message: 'timed out', retryable: true }], s)
    expect(s.messages[0]).toMatchObject({ id: 'u1' })
    expect(s.messages[0]!.localStatus).toBeUndefined()
    expect(s.streamingText).toBe('')
    expect(s.error?.retryable).toBe(true)
    expect(lastUserMessage(s)?.id).toBe('u1')
  })

  it('sending again clears the previous error and drops failed bubbles', () => {
    let s = run([{ type: 'error', code: 'x', message: 'boom', retryable: true }], send(initialChatState))
    s = send(s, 'second try', 'tmp-2')
    expect(s.error).toBeNull()
    expect(s.messages.map((m) => m.id)).toEqual(['tmp-2'])
  })

  it('cancelled returns to idle and drops the partial stream', () => {
    const s = run([{ type: 'token', delta: 'partial' }, { type: 'cancelled' }], send(initialChatState))
    expect(s).toMatchObject({ status: 'idle', stage: null, streamingText: '' })
  })

  it('regenerate removes everything after the last user message and re-enters running', () => {
    const detail: ConversationDetail = {
      ...conversation(),
      messages: [msg({ id: 'u1', seq: 1, role: 'user', content: 'q' }), msg({ id: 'a1', seq: 2, role: 'assistant', content: 'old answer' })],
    }
    let s = chatReducer(initialChatState, { type: 'load', detail })
    s = chatReducer(s, { type: 'regenerate' })
    expect(s.messages.map((m) => m.id)).toEqual(['u1'])
    expect(s.status).toBe('running')
    s = run([{ type: 'message', message: msg({ id: 'a2', seq: 2, role: 'assistant', content: 'new answer' }) }, { type: 'done', execution_id: 'r2', status: 'completed' }], s)
    expect(s.messages.map((m) => m.content)).toEqual(['q', 'new answer'])
  })

  it('reset and dismiss_error', () => {
    const s = run([{ type: 'error', code: 'x', message: 'm', retryable: false }], send(initialChatState))
    expect(chatReducer(s, { type: 'dismiss_error' }).error).toBeNull()
    expect(chatReducer(s, { type: 'reset' })).toEqual(initialChatState)
  })
})

describe('REST fallback', () => {
  it('converts a ChatOut into the same events the socket produces, and the reducer reaches the same state', () => {
    const events = chatOutToEvents({
      conversation: conversation(),
      user_message: msg({ id: 'u1', seq: 1, role: 'user', content: 'hi' }),
      assistant_message: msg({ id: 'a1', seq: 2, role: 'assistant', content: 'hello' }),
      messages: [msg({ id: 'a1', seq: 2, role: 'assistant', content: 'hello' })],
      pending_confirmation: null,
      language: 'en',
      execution_id: 'run-9',
    })
    expect(events.map((e) => e.type)).toEqual(['conversation', 'language', 'user_message', 'message', 'done'])
    const s = run(events, send(initialChatState, 'hi'))
    expect(s.messages.map((m) => m.id)).toEqual(['u1', 'a1'])
    expect(s.status).toBe('idle')
  })

  it("a confirm reply's tool_executions update the existing tool card with the outcome", () => {
    // State before: the booking is waiting for the user's OK.
    let s = run([
      { type: 'message', message: msg({ id: 'a1', seq: 2, role: 'assistant', content: 'Book it?', pending_confirmation: true, tool_executions: [tool({ status: 'awaiting_confirmation' })] }) },
      { type: 'done', execution_id: 'run-1', status: 'awaiting_confirmation' },
    ])
    s = chatReducer(s, { type: 'confirm', executionId: 'tool-1' })
    // REST confirm reply: only the final message is in `messages`; the executed tool arrives via tool_executions.
    const events = chatOutToEvents({
      conversation: conversation(), user_message: null, assistant_message: null,
      messages: [msg({ id: 'a2', seq: 4, role: 'assistant', content: 'You are booked.', tools_used: ['book_appointment'], source: 'tool' })],
      tool_executions: [tool({ status: 'success', summary: 'Booked AP-7K3QX', result: { reference: 'AP-7K3QX' } })],
      pending_confirmation: null, language: 'en', execution_id: 'run-1',
    })
    s = run(events, s)
    expect(s.messages[0]!.tool_executions[0]).toMatchObject({ status: 'success', result: { reference: 'AP-7K3QX' } })
    expect(pendingConfirmation(s)).toBeNull()
    expect(s.messages.at(-1)).toMatchObject({ id: 'a2', content: 'You are booked.' })
    expect(s.status).toBe('idle')
  })

  it('reports awaiting_confirmation when the reply has a pending tool call', () => {
    const pending = tool({ status: 'awaiting_confirmation' })
    const events = chatOutToEvents({
      conversation: conversation(), user_message: null, assistant_message: null,
      messages: [msg({ id: 'a1', seq: 2, role: 'assistant', content: 'Confirm?', pending_confirmation: true, tool_executions: [pending] })],
      pending_confirmation: pending, language: 'en', execution_id: 'run-9',
    })
    const s = run(events)
    expect(events.at(-1)).toMatchObject({ type: 'done', status: 'awaiting_confirmation' })
    expect(s.status).toBe('awaiting_confirmation')
  })
})
