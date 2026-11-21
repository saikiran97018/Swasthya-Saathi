import { useEffect, useMemo, useRef } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import { api } from '@/api/endpoints'
import { qk, useCallTranscript, usePrefs } from '@/api/hooks'
import type { ToolExecution } from '@/api/types'
import { MessageBubble } from '@/components/chat/MessageBubble'
import { useToast } from '@/components/ui/Toast'
import { Skeleton } from '@/components/ui/primitives'
import { UI_ACTIONS_EVENT } from '@/lib/uiActions'

const noop = () => undefined
const NO_AUDIO = { active: false, paused: false, canSpeak: false }

/**
 * The conversation behind a live call, using the same message bubbles, tool cards and confirm/cancel card as the
 * chat screen. Polls while the call is live. Confirming goes through the same endpoint as in chat.
 */
export function CallTranscript({ conversationId, live }: { conversationId: string; live: boolean }) {
  const { data, isLoading, isError } = useCallTranscript(conversationId, live)
  const { data: prefs } = usePrefs()
  const qc = useQueryClient()
  const toast = useToast()
  const messages = data?.messages ?? []
  const scroller = useRef<HTMLDivElement>(null)
  const stick = useRef(true)

  const confirm = useMutation({
    mutationFn: ({ id, approve }: { id: string; approve: boolean }) => api.confirm(id, approve),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.callTranscript(conversationId) }),
    onError: (e: Error) => toast.error(e.message || 'Could not send your answer. Say yes or no out loud instead.'),
  })

  const awaiting = useMemo(() => messages.some((m) => m.tool_executions.some((t) => t.status === 'awaiting_confirmation')), [messages])

  // Hand the assistant's "open this page / change theme" instructions to the app (the runner checks and carries them out once).
  useEffect(() => {
    const execs = messages.flatMap((m) => m.tool_executions).filter((t) => t.tool_name === 'control_app')
    if (execs.length) window.dispatchEvent(new CustomEvent(UI_ACTIONS_EVENT, { detail: execs }))
  }, [messages])

  useEffect(() => {
    if (stick.current) scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' })
  }, [messages.length, awaiting, messages.at(-1)?.content])

  return (
    <section aria-labelledby="transcript-h" className="card overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
        <h2 id="transcript-h" className="text-sm font-semibold">
          {live ? 'Live transcript' : 'Transcript'}
        </h2>
        {!live && messages.length > 0 && (
          <Link to={`/chat/${conversationId}`} className="inline-flex min-h-11 items-center gap-1 text-sm font-semibold text-accent-text hover:underline">
            View conversation <ArrowRight className="size-4" aria-hidden />
          </Link>
        )}
      </div>

      {awaiting && live && (
        <p className="border-b border-line bg-saffron-soft/50 px-4 py-2 text-sm text-saffron-text" role="status">
          You can also just say yes or no.
        </p>
      )}

      <div
        ref={scroller}
        onScroll={() => {
          const el = scroller.current
          if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
        }}
        className="scroll-thin max-h-[26rem] min-h-40 overflow-y-auto overflow-x-hidden px-4 py-4"
        aria-live="polite"
        aria-relevant="additions"
      >
        {isLoading ? (
          <div className="space-y-3" aria-busy>
            <Skeleton className="h-10 w-2/3" />
            <Skeleton className="ml-auto h-10 w-1/2" />
          </div>
        ) : messages.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted">{isError ? 'The transcript could not be loaded yet. It will keep trying.' : live ? 'What you and your assistant say will appear here.' : 'Nothing was said in this call.'}</p>
        ) : (
          <div className="flex flex-col gap-5">
            {messages.map((m) => (
              <MessageBubble
                key={m.id}
                message={m}
                isLatestAssistant={false}
                turnRunning={confirm.isPending}
                showToolDetails={prefs?.show_tool_details ?? true}
                audio={NO_AUDIO}
                onPlay={noop}
                onStopAudio={noop}
                onPause={noop}
                onResume={noop}
                onRegenerate={noop}
                onRetryUnsent={noop}
                onConfirm={(tool: ToolExecution, approve: boolean) => confirm.mutate({ id: tool.id, approve })}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
