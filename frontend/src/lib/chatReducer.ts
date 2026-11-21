import type { Conversation, ConversationDetail, Message, ServerEvent, Stage, ToolExecution, UiMessage } from '@/api/types'

/**
 * The single source of truth for a live conversation. Every WebSocket event (and every REST
 * fallback reply, converted to events) goes through `chatReducer`, so streaming, tool cards,
 * confirmations, errors and cancellation behave identically however the data arrives.
 */

export type TurnStatus = 'idle' | 'running' | 'awaiting_confirmation'

export interface ChatError {
  code: string
  message: string
  retryable: boolean
}

export interface ChatState {
  conversationId: string | null
  conversation: Conversation | null
  messages: UiMessage[]
  streamingText: string
  stage: Stage | null
  status: TurnStatus
  language: string | null
  error: ChatError | null
  executionId: string | null
}

export const initialChatState: ChatState = {
  conversationId: null,
  conversation: null,
  messages: [],
  streamingText: '',
  stage: null,
  status: 'idle',
  language: null,
  error: null,
  executionId: null,
}

export type ChatAction =
  | { type: 'reset' }
  | { type: 'load'; detail: ConversationDetail }
  | { type: 'send'; text: string; inputMode: 'text' | 'voice'; tempId: string; now?: string }
  | { type: 'regenerate' }
  | { type: 'confirm'; executionId: string }
  | { type: 'local_cancel' }
  | { type: 'local_error'; error: ChatError }
  | { type: 'dismiss_error' }
  | { type: 'event'; event: ServerEvent }

const TEMP_PREFIX = 'tmp-'
export const isTempId = (id: string) => id.startsWith(TEMP_PREFIX)
export const makeTempId = () => `${TEMP_PREFIX}${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`

function bySeq(a: UiMessage, b: UiMessage): number {
  // optimistic (temp) messages have no real seq yet: keep them after everything else
  const as = isTempId(a.id) ? Number.MAX_SAFE_INTEGER : a.seq
  const bs = isTempId(b.id) ? Number.MAX_SAFE_INTEGER : b.seq
  return as - bs
}

function upsertMessage(messages: UiMessage[], incoming: Message): UiMessage[] {
  const idx = messages.findIndex((m) => m.id === incoming.id)
  const next = idx >= 0 ? messages.map((m, i) => (i === idx ? { ...incoming } : m)) : [...messages, { ...incoming }]
  return next.sort(bySeq)
}

function mergeToolExecution(messages: UiMessage[], exec: ToolExecution): UiMessage[] {
  if (!exec.assistant_message_id) return messages
  return messages.map((m) => {
    if (m.id !== exec.assistant_message_id) return m
    const existing = m.tool_executions.some((t) => t.id === exec.id)
    const tool_executions = existing ? m.tool_executions.map((t) => (t.id === exec.id ? exec : t)) : [...m.tool_executions, exec]
    return { ...m, tool_executions, pending_confirmation: tool_executions.some((t) => t.status === 'awaiting_confirmation') }
  })
}

/** The tool call (if any) currently waiting for the user's yes/no. */
export function pendingConfirmation(state: ChatState): ToolExecution | null {
  for (let i = state.messages.length - 1; i >= 0; i--) {
    const found = state.messages[i]?.tool_executions.find((t) => t.status === 'awaiting_confirmation')
    if (found) return found
  }
  return null
}

export function lastUserMessage(state: ChatState): UiMessage | undefined {
  for (let i = state.messages.length - 1; i >= 0; i--) if (state.messages[i]?.role === 'user') return state.messages[i]
  return undefined
}

export function lastAssistantMessage(state: ChatState): UiMessage | undefined {
  const last = state.messages[state.messages.length - 1]
  return last?.role === 'assistant' ? last : undefined
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case 'reset':
      return { ...initialChatState }

    case 'load': {
      const d = action.detail
      const { messages: serverMessages, ...conversation } = d
      const messages = [...serverMessages].sort(bySeq)
      const awaiting = messages.some((m) => m.pending_confirmation)
      return {
        ...initialChatState,
        conversationId: d.id,
        conversation,
        messages,
        language: d.language,
        status: awaiting ? 'awaiting_confirmation' : 'idle',
      }
    }

    case 'send': {
      const temp: UiMessage = {
        id: action.tempId,
        conversation_id: state.conversationId ?? '',
        seq: Number.MAX_SAFE_INTEGER,
        role: 'user',
        content: action.text,
        language: state.language,
        input_mode: action.inputMode,
        source: 'user',
        tools_used: [],
        tool_executions: [],
        pending_confirmation: false,
        created_at: action.now ?? new Date().toISOString(),
        localStatus: 'sending',
      }
      // Sending a new message abandons any unanswered confirmation: the backend cancels it too.
      const messages = state.messages
        .filter((m) => !(m.localStatus === 'failed'))
        .map((m) =>
          m.pending_confirmation
            ? { ...m, pending_confirmation: false, tool_executions: m.tool_executions.map((t) => (t.status === 'awaiting_confirmation' ? { ...t, status: 'cancelled' as const } : t)) }
            : m,
        )
      return { ...state, messages: [...messages, temp], status: 'running', stage: 'thinking', streamingText: '', error: null }
    }

    case 'regenerate': {
      // Drop everything after the last user message; the backend does the same before re-running.
      let lastUser = -1
      state.messages.forEach((m, i) => {
        if (m.role === 'user') lastUser = i
      })
      const messages = lastUser >= 0 ? state.messages.slice(0, lastUser + 1) : state.messages
      return { ...state, messages, status: 'running', stage: 'thinking', streamingText: '', error: null }
    }

    case 'confirm': {
      const messages = state.messages.map((m) => ({
        ...m,
        pending_confirmation: false,
        tool_executions: m.tool_executions.map((t) => (t.id === action.executionId ? { ...t, status: 'running' as const } : t)),
      }))
      return { ...state, messages, status: 'running', stage: 'tool', streamingText: '', error: null }
    }

    case 'local_cancel':
      return { ...state, status: 'idle', stage: null, streamingText: '' }

    case 'local_error':
      return failTurn(state, action.error)

    case 'dismiss_error':
      return { ...state, error: null }

    case 'event':
      return applyEvent(state, action.event)
  }
}

function failTurn(state: ChatState, error: ChatError): ChatState {
  return {
    ...state,
    // a message that never reached the server is marked failed so the UI can offer "Retry"
    messages: state.messages.map((m) => (isTempId(m.id) ? { ...m, localStatus: 'failed' as const } : m)),
    status: 'idle',
    stage: null,
    streamingText: '',
    error,
  }
}

function applyEvent(state: ChatState, ev: ServerEvent): ChatState {
  switch (ev.type) {
    case 'conversation':
      return { ...state, conversationId: ev.conversation.id, conversation: ev.conversation }

    case 'language':
      return { ...state, language: ev.language }

    case 'user_message': {
      // Replace the optimistic bubble with the real message (same text), or just upsert on regenerate/REST.
      const tempIdx = state.messages.findIndex((m) => isTempId(m.id) && m.localStatus === 'sending')
      if (tempIdx >= 0) {
        const messages = state.messages.map((m, i) => (i === tempIdx ? { ...ev.message } : m)).sort(bySeq)
        return { ...state, messages }
      }
      return { ...state, messages: upsertMessage(state.messages, ev.message) }
    }

    case 'stage':
      return { ...state, stage: ev.stage }

    case 'token':
      return { ...state, streamingText: state.streamingText + ev.delta, stage: 'responding' }

    case 'message': {
      const messages = upsertMessage(state.messages, ev.message)
      // The streamed bubble is replaced by the persisted assistant message.
      return { ...state, messages, streamingText: ev.message.role === 'assistant' ? '' : state.streamingText }
    }

    case 'tool_start':
    case 'tool_result':
    case 'confirmation_required': {
      const messages = mergeToolExecution(state.messages, ev.tool_execution)
      return { ...state, messages, stage: ev.type === 'tool_start' ? 'tool' : state.stage }
    }

    case 'error':
      return failTurn(state, { code: ev.code, message: ev.message, retryable: ev.retryable })

    case 'cancelled':
      return { ...state, status: 'idle', stage: null, streamingText: '' }

    case 'done':
      return {
        ...state,
        status: ev.status === 'awaiting_confirmation' ? 'awaiting_confirmation' : 'idle',
        stage: null,
        streamingText: '',
        executionId: ev.execution_id,
        language: ev.language ?? state.language,
      }

    case 'pong':
      return state
  }
}
