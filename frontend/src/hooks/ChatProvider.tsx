import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ApiError } from '@/api/client'
import { api } from '@/api/endpoints'
import { qk, usePrefs } from '@/api/hooks'
import type { ChatOut, ClientCommand, ServerEvent } from '@/api/types'
import { chatReducer, initialChatState, isTempId, lastUserMessage, makeTempId, type ChatState } from '@/lib/chatReducer'
import { ChatSocket, chatOutToEvents, type ConnectionStatus } from '@/lib/chatSocket'
import { AUTO_LANGUAGE, languageToSend, ttsAvailable } from '@/lib/language'
import { speechPlayer } from '@/lib/speechPlayer'
import { SpeechStreamer } from '@/lib/speechStreamer'
import { rememberAudio } from '@/lib/ttsCache'
import { useLanguage } from './LanguageProvider'

export interface SendOptions {
  inputMode?: 'text' | 'voice'
  /** Read the reply aloud as it streams (voice screen). */
  voiceOutput?: boolean
  /** Force a language for this message (and make it the selected one). */
  language?: string
}

interface ChatCtx {
  state: ChatState
  connection: ConnectionStatus
  /** True while messages travel over REST because the WebSocket is unavailable. */
  limitedMode: boolean
  loadingConversation: boolean
  loadError: string | null
  /** Voice replies on/off for the voice screen (a session-level mute). */
  speakReplies: boolean
  setSpeakReplies: (v: boolean) => void
  sendMessage: (text: string, opts?: SendOptions) => void
  regenerate: () => void
  confirm: (executionId: string, approve: boolean) => void
  cancel: () => void
  retry: () => void
  dismissError: () => void
  /** Text to place in the composer without sending it (e.g. from a notification or appointment action). */
  draft: { text: string; nonce: number } | null
  setDraft: (text: string) => void
  clearDraft: () => void
  startNew: () => void
  openConversation: (id: string) => Promise<void>
}

const Ctx = createContext<ChatCtx | null>(null)

type LastCommand = { kind: 'message'; text: string; opts: SendOptions } | { kind: 'regenerate' } | { kind: 'confirm'; executionId: string; approve: boolean }

function errorFrom(err: unknown) {
  if (err instanceof ApiError) return { code: err.code, message: err.message, retryable: err.status === 0 || err.status >= 500 || err.status === 429 || err.code.startsWith('llm_') }
  return { code: 'unknown', message: 'Something went wrong. Please try again.', retryable: true }
}

export function ChatProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const { selected, setSelected, languages } = useLanguage()
  const { data: prefs } = usePrefs()

  const [state, dispatch] = useReducer(chatReducer, initialChatState)
  const [connection, setConnection] = useState<ConnectionStatus>('connecting')
  const [limitedMode, setLimitedMode] = useState(false)
  const [loadingConversation, setLoadingConversation] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [speakReplies, setSpeakReplies] = useState(true)
  const [draft, setDraftState] = useState<{ text: string; nonce: number } | null>(null)
  const setDraft = useCallback((text: string) => setDraftState({ text, nonce: Date.now() }), [])
  const clearDraft = useCallback(() => setDraftState(null), [])

  // Latest values for use inside long-lived callbacks (socket handlers).
  const stateRef = useRef(state)
  stateRef.current = state
  const selectedRef = useRef(selected)
  selectedRef.current = selected
  const prefsRef = useRef(prefs)
  prefsRef.current = prefs
  const languagesRef = useRef(languages)
  languagesRef.current = languages
  const speakRepliesRef = useRef(speakReplies)
  speakRepliesRef.current = speakReplies

  const socketRef = useRef<ChatSocket | null>(null)
  const voiceTurn = useRef(false)
  const lastCommand = useRef<LastCommand | null>(null)
  const requestSeq = useRef(0) // drops REST replies that were cancelled / superseded
  const openSeq = useRef(0)

  const speakingAllowed = useCallback(() => {
    const p = prefsRef.current
    const lang = stateRef.current.language ?? stateRef.current.conversation?.language
    return !!p?.voice_output_enabled && !!p.auto_play_responses && speakRepliesRef.current && ttsAvailable(lang, languagesRef.current)
  }, [])

  const streamer = useMemo(
    () =>
      new SpeechStreamer({
        synthesize: (text) => {
          const lang = stateRef.current.language ?? stateRef.current.conversation?.language ?? 'en'
          return api.synthesize(text, lang, prefsRef.current?.tts_gender)
        },
        enqueue: (id, blob) => speechPlayer.enqueue(id, blob),
        remember: rememberAudio,
      }),
    [],
  )

  const handleEvent = useCallback(
    (event: ServerEvent) => {
      dispatch({ type: 'event', event })
      if (voiceTurn.current && speakingAllowed()) streamer.handle(event)

      if (event.type === 'language' && event.changed && selectedRef.current !== AUTO_LANGUAGE) setSelected(event.language)
      if (event.type === 'done' || event.type === 'error' || event.type === 'cancelled') {
        void qc.invalidateQueries({ queryKey: qk.conversationsAll })
        void qc.invalidateQueries({ queryKey: qk.dashboard })
        void qc.invalidateQueries({ queryKey: qk.executions })
        void qc.invalidateQueries({ queryKey: qk.tasksAll })
        void qc.invalidateQueries({ queryKey: ['appointments'] })
        void qc.invalidateQueries({ queryKey: ['notifications'] })
      }
    },
    [qc, setSelected, speakingAllowed, streamer],
  )

  // One WebSocket for the whole app session.
  useEffect(() => {
    const socket = new ChatSocket({ onEvent: handleEvent, onStatus: setConnection })
    socketRef.current = socket
    socket.start()
    return () => socket.stop()
  }, [handleEvent])

  /** Run a REST request and replay its result through the reducer as if it had streamed. */
  const viaRest = useCallback(
    async (call: () => Promise<ChatOut>) => {
      const seq = ++requestSeq.current
      setLimitedMode(true)
      try {
        const out = await call()
        if (seq !== requestSeq.current) return
        chatOutToEvents(out).forEach(handleEvent)
      } catch (err) {
        if (seq !== requestSeq.current) return
        const e = errorFrom(err)
        handleEvent({ type: 'error', code: e.code, message: e.message, retryable: e.retryable })
      }
    },
    [handleEvent],
  )

  const transmit = useCallback(
    (cmd: ClientCommand, rest: () => Promise<ChatOut>) => {
      if (socketRef.current?.send(cmd)) {
        setLimitedMode(false)
        return
      }
      void viaRest(rest)
    },
    [viaRest],
  )

  const sendMessage = useCallback(
    (text: string, opts: SendOptions = {}) => {
      const clean = text.trim()
      if (!clean || stateRef.current.status === 'running') return
      speechPlayer.stop()
      streamer.reset()
      if (opts.language) setSelected(opts.language)
      const language = opts.language ?? languageToSend(selectedRef.current)
      const inputMode = opts.inputMode ?? 'text'
      const voiceOutput = !!opts.voiceOutput
      voiceTurn.current = voiceOutput
      lastCommand.current = { kind: 'message', text: clean, opts: { ...opts, language: undefined } }

      const conversationId = stateRef.current.conversationId
      dispatch({ type: 'send', text: clean, inputMode, tempId: makeTempId() })
      transmit(
        { type: 'message', text: clean, conversation_id: conversationId, input_mode: inputMode, language, voice_output: voiceOutput },
        () => api.chat({ conversation_id: conversationId, message: clean, input_mode: inputMode, language, voice_output: voiceOutput }),
      )
    },
    [setSelected, streamer, transmit],
  )

  const regenerate = useCallback(() => {
    const id = stateRef.current.conversationId
    if (!id || stateRef.current.status === 'running') return
    speechPlayer.stop()
    streamer.reset()
    lastCommand.current = { kind: 'regenerate' }
    dispatch({ type: 'regenerate' })
    transmit({ type: 'regenerate', conversation_id: id, voice_output: voiceTurn.current }, () => api.chat({ conversation_id: id, regenerate: true, voice_output: voiceTurn.current }))
  }, [streamer, transmit])

  const confirm = useCallback(
    (executionId: string, approve: boolean) => {
      if (stateRef.current.status === 'running') return
      lastCommand.current = { kind: 'confirm', executionId, approve }
      streamer.reset()
      dispatch({ type: 'confirm', executionId })
      transmit({ type: 'confirm', execution_id: executionId, approve, voice_output: voiceTurn.current }, () => api.confirm(executionId, approve))
    },
    [streamer, transmit],
  )

  const cancel = useCallback(() => {
    speechPlayer.stop()
    streamer.reset()
    if (!socketRef.current?.send({ type: 'cancel' })) {
      requestSeq.current++ // ignore the pending REST reply
      dispatch({ type: 'local_cancel' })
    }
  }, [streamer])

  const retry = useCallback(() => {
    const s = stateRef.current
    const last = lastCommand.current
    if (s.status === 'running' || !last) return
    if (last.kind === 'confirm') return confirm(last.executionId, last.approve)
    // If the server never stored the user's message, send it again; otherwise just re-run the answer.
    if (last.kind === 'message' && lastUserMessage(s) && isTempId(lastUserMessage(s)!.id)) {
      dispatch({ type: 'dismiss_error' })
      return sendMessage(last.text, last.opts)
    }
    if (s.conversationId) {
      dispatch({ type: 'dismiss_error' })
      return regenerate()
    }
    if (last.kind === 'message') sendMessage(last.text, last.opts)
  }, [confirm, regenerate, sendMessage])

  const startNew = useCallback(() => {
    openSeq.current++
    if (stateRef.current.status === 'running') socketRef.current?.send({ type: 'cancel' })
    requestSeq.current++
    speechPlayer.stop()
    streamer.reset()
    lastCommand.current = null
    setLoadError(null)
    setLoadingConversation(false)
    dispatch({ type: 'reset' })
  }, [streamer])

  const openConversation = useCallback(
    async (id: string) => {
      if (stateRef.current.conversationId === id) return
      const seq = ++openSeq.current
      if (stateRef.current.status === 'running') socketRef.current?.send({ type: 'cancel' })
      requestSeq.current++
      speechPlayer.stop()
      streamer.reset()
      lastCommand.current = null
      dispatch({ type: 'reset' })
      setLoadError(null)
      setLoadingConversation(true)
      try {
        const detail = await qc.fetchQuery({ queryKey: qk.conversation(id), queryFn: () => api.conversation(id), staleTime: 0 })
        if (seq !== openSeq.current) return
        dispatch({ type: 'load', detail })
        if (selectedRef.current !== AUTO_LANGUAGE) setSelected(detail.language)
      } catch (err) {
        if (seq !== openSeq.current) return
        setLoadError(err instanceof ApiError && err.status === 404 ? 'This conversation was not found. It may have been deleted.' : err instanceof ApiError ? err.message : 'Could not load this conversation.')
      } finally {
        if (seq === openSeq.current) setLoadingConversation(false)
      }
    },
    [qc, setSelected, streamer],
  )

  const value = useMemo<ChatCtx>(
    () => ({
      state, connection, limitedMode, loadingConversation, loadError, speakReplies, setSpeakReplies,
      sendMessage, regenerate, confirm, cancel, retry, dismissError: () => dispatch({ type: 'dismiss_error' }), draft, setDraft, clearDraft, startNew, openConversation,
    }),
    [state, connection, limitedMode, loadingConversation, loadError, speakReplies, sendMessage, regenerate, confirm, cancel, retry, draft, setDraft, clearDraft, startNew, openConversation],
  )

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useChat(): ChatCtx {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useChat must be used inside <ChatProvider>')
  return ctx
}
