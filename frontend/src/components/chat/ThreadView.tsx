import { useEffect, useMemo, useRef } from 'react'
import { LoaderCircle, RotateCw, X } from 'lucide-react'
import { usePrefs } from '@/api/hooks'
import { LogoMark } from '@/components/layout/Brand'
import { Button, IconButton, Skeleton } from '@/components/ui/primitives'
import { useChat } from '@/hooks/ChatProvider'
import { useSpeech } from '@/hooks/useSpeech'
import { cn } from '@/lib/format'
import { Markdown } from './Markdown'
import { MessageBubble } from './MessageBubble'

const STAGE_LABEL = { thinking: 'Thinking…', tool: 'Working on it…', responding: 'Writing…' } as const

export function TypingIndicator({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3" role="status" aria-live="polite">
      <LogoMark className="size-8" />
      <div className="card inline-flex items-center gap-2.5 rounded-2xl rounded-tl-md px-4 py-3 text-sm text-muted">
        <span className="flex gap-1" aria-hidden>
          {[0, 1, 2].map((i) => (
            <span key={i} className="anim-dot size-1.5 rounded-full bg-accent" style={{ animationDelay: `${i * 0.15}s` }} />
          ))}
        </span>
        {label}
      </div>
    </div>
  )
}

const ERROR_HINT: Record<string, string> = {
  llm_not_configured: 'The AI model is not set up yet. Add LLM_API_KEY in the backend .env file, then try again.',
  bhashini_not_configured: 'Speech is not set up yet. Add the Bhashini keys in the backend .env file.',
  rate_limited: 'You are sending messages very quickly. Wait a moment and try again.',
}

export function ErrorBanner({ className }: { className?: string }) {
  const { state, retry, dismissError } = useChat()
  const e = state.error
  if (!e) return null
  return (
    <div role="alert" className={cn('flex items-start gap-3 rounded-xl border border-danger/30 bg-danger-soft px-3.5 py-3 text-sm', className)}>
      <div className="min-w-0 flex-1">
        <div className="font-medium text-danger">{ERROR_HINT[e.code] ?? e.message}</div>
        {ERROR_HINT[e.code] && e.message && <div className="mt-0.5 text-xs text-muted">{e.message}</div>}
      </div>
      {e.retryable || state.messages.length > 0 ? (
        <Button size="sm" variant="secondary" onClick={retry}>
          <RotateCw className="size-3.5" aria-hidden /> Retry
        </Button>
      ) : null}
      <IconButton label="Dismiss error" size="sm" onClick={dismissError}>
        <X className="size-4" />
      </IconButton>
    </div>
  )
}

/** The scrolling message list, live stream bubble, typing indicator and error banner. */
export function ThreadView({ className, children }: { className?: string; children?: React.ReactNode }) {
  const chat = useChat()
  const { state, loadingConversation, loadError } = chat
  const { data: prefs } = usePrefs()
  const speech = useSpeech()
  const bottom = useRef<HTMLDivElement>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const stick = useRef(true)

  const lastAssistantId = useMemo(() => [...state.messages].reverse().find((m) => m.role === 'assistant')?.id, [state.messages])
  const running = state.status === 'running'
  const lang = state.language ?? state.conversation?.language

  // Keep the newest content in view, unless the user scrolled up to read.
  useEffect(() => {
    if (stick.current) bottom.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [state.messages, state.streamingText, running, state.error])

  const onScroll = () => {
    const el = scroller.current
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120
  }

  if (loadingConversation) {
    return (
      <div className={cn('mx-auto w-full max-w-3xl space-y-6 p-4 md:p-6', className)} aria-busy>
        <Skeleton className="ml-auto h-10 w-2/5" />
        <Skeleton className="h-24 w-4/5" />
        <Skeleton className="ml-auto h-10 w-1/3" />
      </div>
    )
  }
  if (loadError) {
    return (
      <div className="mx-auto max-w-md p-10 text-center" role="alert">
        <p className="font-medium text-danger">{loadError}</p>
      </div>
    )
  }

  return (
    <div ref={scroller} onScroll={onScroll} className={cn('scroll-thin min-h-0 flex-1 overflow-y-auto', className)}>
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-4 py-6 md:px-6">
        {state.messages.length === 0 && !running && children}

        {state.messages.map((m) => (
          <MessageBubble
            key={m.id}
            message={m}
            isLatestAssistant={m.id === lastAssistantId}
            turnRunning={running}
            showToolDetails={prefs?.show_tool_details ?? true}
            audio={{ active: speech.isActive(m, m.id === lastAssistantId), paused: speech.snapshot.status === 'paused', canSpeak: speech.canSpeak(m.language ?? lang) }}
            onPlay={() => speech.speakMessage(m, lang)}
            onStopAudio={speech.stop}
            onPause={speech.pause}
            onResume={speech.resume}
            onRegenerate={chat.regenerate}
            onRetryUnsent={chat.retry}
            onConfirm={(tool, approve) => chat.confirm(tool.id, approve)}
          />
        ))}

        {running && state.streamingText && (
          <div className="flex gap-3">
            <LogoMark className="mt-0.5 size-8" />
            <div className="card inline-block max-w-full rounded-2xl rounded-tl-md px-4 py-3 sm:max-w-[85%]">
              <Markdown>{state.streamingText}</Markdown>
              <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-accent align-middle" aria-hidden />
            </div>
          </div>
        )}

        {running && !state.streamingText && <TypingIndicator label={STAGE_LABEL[state.stage ?? 'thinking']} />}

        {state.status === 'awaiting_confirmation' && !running && state.messages.length > 0 && (
          <p className="flex items-center gap-2 px-1 text-sm text-muted">
            <LoaderCircle className="size-4 text-warn" aria-hidden /> Waiting for your confirmation above.
          </p>
        )}

        <ErrorBanner />
        <div ref={bottom} className="h-px" />
      </div>
    </div>
  )
}
