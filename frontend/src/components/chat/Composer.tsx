import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { ArrowUp, LoaderCircle, Mic, Square, X } from 'lucide-react'
import { usePrefs } from '@/api/hooks'
import { IconButton } from '@/components/ui/primitives'
import { useChat } from '@/hooks/ChatProvider'
import { useLanguage } from '@/hooks/LanguageProvider'
import { useDictation } from '@/hooks/useDictation'
import { asrAvailable, nativeName, speechLanguage } from '@/lib/language'
import { cn } from '@/lib/format'

const MAX_CHARS = 4000

/**
 * Text composer with dictation. Dictated text is placed in the box so it can be corrected before
 * sending (unless "Send voice messages automatically" is on in settings).
 */
export function Composer({
  placeholder = 'Describe how you feel, or ask for an appointment…',
  autoFocus,
  voiceOutput = false,
  hideMic = false,
}: {
  placeholder?: string
  autoFocus?: boolean
  /** Read replies aloud (the voice screen). */
  voiceOutput?: boolean
  /** Hide the dictation button (the voice screen has its own big mic). */
  hideMic?: boolean
}) {
  const { state, sendMessage, cancel, draft, clearDraft } = useChat()
  const { selected, languages } = useLanguage()
  const { data: prefs } = usePrefs()
  const [text, setText] = useState('')
  const [dictated, setDictated] = useState(false)
  const box = useRef<HTMLTextAreaElement>(null)
  const running = state.status === 'running'

  const convLang = state.language ?? state.conversation?.language
  const getLanguage = () => speechLanguage(selected, convLang, prefs?.primary_language)

  const dictation = useDictation({
    getLanguage,
    silenceMs: prefs?.silence_timeout_ms ?? 1500,
    onResult: (r) => {
      if (prefs?.auto_send_voice !== false) { // on unless the person turned it off (also while settings are still loading)
        sendMessage(r.text, { inputMode: 'voice', voiceOutput })
        return
      }
      setText((cur) => (cur.trim() ? `${cur.trim()} ${r.text}` : r.text))
      setDictated(true)
      box.current?.focus()
    },
  })

  // Auto-grow the textarea up to ~8 lines.
  useEffect(() => {
    const el = box.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [text])

  useEffect(() => {
    if (autoFocus) box.current?.focus()
  }, [autoFocus])

  // A draft handed over from a notification / appointment action: fill the box, never send it.
  useEffect(() => {
    if (!draft) return
    setText(draft.text.slice(0, MAX_CHARS))
    setDictated(false)
    clearDraft()
    window.setTimeout(() => {
      const el = box.current
      if (el) {
        el.focus()
        el.setSelectionRange(el.value.length, el.value.length)
      }
    }, 0)
  }, [draft, clearDraft])

  const submit = () => {
    const value = text.trim()
    if (!value || running) return
    sendMessage(value, { inputMode: dictated ? 'voice' : 'text', voiceOutput })
    setText('')
    setDictated(false)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // isComposing: don't send while an Indic/CJK input method is still composing a character.
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    }
  }

  const micLang = getLanguage()
  const micAllowed = dictation.supported && asrAvailable(micLang, languages)
  const listening = dictation.status === 'listening' || dictation.status === 'starting'
  const transcribing = dictation.status === 'transcribing'

  return (
    <div className="mx-auto w-full max-w-3xl px-3 pb-3 md:px-6 md:pb-5">
      {dictation.error && (
        <div role="alert" className="mb-2 flex items-start gap-2 rounded-xl border border-danger/30 bg-danger-soft px-3 py-2 text-sm">
          <span className="min-w-0 flex-1 text-danger">{dictation.error}</span>
          <button aria-label="Dismiss" onClick={dictation.clearError} className="rounded p-0.5 text-muted hover:text-fg">
            <X className="size-4" />
          </button>
        </div>
      )}
      {dictated && !listening && !transcribing && (
        <p className="mb-1.5 px-1 text-xs text-muted">Heard in {nativeName(micLang, languages)}. Check the text and fix anything before sending.</p>
      )}

      <div className={cn('card flex items-end gap-1.5 rounded-2xl p-1.5 transition focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/25', listening && 'border-accent')}>
        {!hideMic && (
          <div className="relative">
            <IconButton
              label={listening ? 'Stop recording' : transcribing ? 'Transcribing…' : micAllowed ? `Speak in ${nativeName(micLang, languages)}` : 'Voice input is not available'}
              variant={listening ? 'primary' : 'soft'}
              size="md"
              disabled={!micAllowed || running || transcribing}
              onClick={() => (listening ? dictation.stop() : void dictation.start())}
            >
              {transcribing ? <LoaderCircle className="size-5 animate-spin" /> : listening ? <Square className="size-4 fill-current" /> : <Mic className="size-5" />}
            </IconButton>
            {listening && <span className="anim-ripple pointer-events-none absolute inset-0 rounded-xl border-2 border-accent" aria-hidden />}
          </div>
        )}

        {listening ? (
          <div className="flex min-h-10 flex-1 items-center gap-3 px-2" role="status" aria-live="polite">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-soft">
              <div className="h-full rounded-full bg-accent transition-[width] duration-75" style={{ width: `${Math.max(4, dictation.level * 100)}%` }} />
            </div>
            <span className="text-sm text-muted">Listening… stops when you pause</span>
          </div>
        ) : (
          <textarea
            ref={box}
            value={text}
            onChange={(e) => {
              setText(e.target.value.slice(0, MAX_CHARS))
              if (!e.target.value) setDictated(false)
            }}
            onKeyDown={onKeyDown}
            rows={1}
            placeholder={transcribing ? 'Transcribing…' : placeholder}
            aria-label="Message"
            className="max-h-[200px] min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-[15px] outline-none placeholder:text-muted"
          />
        )}

        {running ? (
          <IconButton label="Stop generating" variant="secondary" onClick={cancel}>
            <Square className="size-4 fill-current" />
          </IconButton>
        ) : (
          <IconButton label="Send message" variant="primary" disabled={!text.trim() || listening || transcribing} onClick={submit}>
            <ArrowUp className="size-5" />
          </IconButton>
        )}
      </div>
      {text.length > MAX_CHARS - 500 && <p className="mt-1 px-2 text-right text-xs text-muted">{text.length}/{MAX_CHARS}</p>}
    </div>
  )
}
