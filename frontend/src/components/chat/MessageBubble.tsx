import { memo, useState } from 'react'
import { Check, Copy, Mic, Pause, Play, RotateCw, Square, TriangleAlert, Volume2, Wrench } from 'lucide-react'
import { ReplyRating } from '@/components/chat/ReplyRating'
import type { ToolExecution, UiMessage } from '@/api/types'
import { LogoMark } from '@/components/layout/Brand'
import { Badge, IconButton } from '@/components/ui/primitives'
import { useToast } from '@/components/ui/Toast'
import { clockTime, cn, humanize } from '@/lib/format'
import { nativeName } from '@/lib/language'
import { Markdown } from './Markdown'
import { ConfirmationCard, ToolCard } from './ToolCard'

interface Props {
  message: UiMessage
  isLatestAssistant: boolean
  turnRunning: boolean
  showToolDetails: boolean
  /** Audio state for this message. */
  audio: { active: boolean; paused: boolean; canSpeak: boolean }
  onPlay: () => void
  onStopAudio: () => void
  onPause: () => void
  onResume: () => void
  onRegenerate: () => void
  onRetryUnsent: () => void
  onConfirm: (tool: ToolExecution, approve: boolean) => void
}

export const MessageBubble = memo(function MessageBubble(p: Props) {
  const m = p.message
  const toast = useToast()
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(m.content)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      toast.error('Could not copy. Select the text and copy it manually.')
    }
  }

  if (m.role === 'user') {
    const failed = m.localStatus === 'failed'
    return (
      <div className="anim-fade-up flex flex-col items-end gap-1">
        <div className={cn('max-w-[88%] rounded-2xl rounded-br-md bg-accent px-4 py-2.5 text-accent-fg shadow-sm sm:max-w-[75%]', m.localStatus === 'sending' && 'opacity-70', failed && 'bg-danger')}>
          <p className="break-words whitespace-pre-wrap">{m.content}</p>
        </div>
        <div className="flex items-center gap-2 px-1 text-xs text-muted">
          {failed ? (
            <>
              <TriangleAlert className="size-3.5 text-danger" aria-hidden />
              <span className="text-danger">Not sent</span>
              <button onClick={p.onRetryUnsent} className="inline-flex items-center gap-1 font-medium text-accent-text underline-offset-2 hover:underline">
                <RotateCw className="size-3" aria-hidden /> Retry
              </button>
            </>
          ) : (
            <>
              {m.input_mode === 'voice' && <Mic className="size-3" aria-label="Spoken message" />}
              {m.language && <span>{nativeName(m.language)}</span>}
              {m.localStatus !== 'sending' && <time dateTime={m.created_at}>{clockTime(m.created_at)}</time>}
            </>
          )}
        </div>
      </div>
    )
  }

  const pending = m.tool_executions.find((t) => t.status === 'awaiting_confirmation')
  const otherTools = m.tool_executions.filter((t) => t.status !== 'awaiting_confirmation')
  const hasText = m.content.trim().length > 0

  return (
    <div className="anim-fade-up flex gap-3">
      <LogoMark className="mt-0.5 size-8" />
      <div className="min-w-0 flex-1 space-y-2">
        {hasText && (
          <div className="card inline-block max-w-full rounded-2xl rounded-tl-md px-4 py-3 sm:max-w-[85%]">
            <Markdown>{m.content}</Markdown>
          </div>
        )}

        {otherTools.length > 0 && (
          <div className="max-w-xl space-y-1.5" aria-label="Actions taken">
            {otherTools.map((t) => (
              <ToolCard key={t.id} tool={t} showDetails={p.showToolDetails} />
            ))}
          </div>
        )}

        {pending && (
          <div className="max-w-xl">
            <ConfirmationCard tool={pending} busy={p.turnRunning} onConfirm={(approve) => p.onConfirm(pending, approve)} />
          </div>
        )}

        {hasText && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1">
            <div className="flex items-center gap-0.5 text-muted">
              <IconButton label={copied ? 'Copied' : 'Copy reply'} size="sm" onClick={copy}>
                {copied ? <Check className="size-4 text-ok" /> : <Copy className="size-4" />}
              </IconButton>
              {p.audio.canSpeak &&
                (p.audio.active ? (
                  <>
                    <IconButton label={p.audio.paused ? 'Resume audio' : 'Pause audio'} size="sm" onClick={p.audio.paused ? p.onResume : p.onPause}>
                      {p.audio.paused ? <Play className="size-4" /> : <Pause className="size-4" />}
                    </IconButton>
                    <IconButton label="Stop audio" size="sm" onClick={p.onStopAudio}>
                      <Square className="size-4" />
                    </IconButton>
                  </>
                ) : (
                  <IconButton label="Play reply aloud" size="sm" onClick={p.onPlay}>
                    <Volume2 className="size-4" />
                  </IconButton>
                ))}
              {p.isLatestAssistant && !p.turnRunning && (
                <IconButton label="Regenerate reply" size="sm" onClick={p.onRegenerate}>
                  <RotateCw className="size-4" />
                </IconButton>
              )}
              {!p.turnRunning && <ReplyRating messageId={m.id} />}
            </div>
            <SourceBadge message={m} />
            <span className="flex items-center gap-1.5 text-xs text-muted">
              {m.language && <span>{nativeName(m.language)}</span>}
              <time dateTime={m.created_at}>{clockTime(m.created_at)}</time>
            </span>
          </div>
        )}
      </div>
    </div>
  )
})

/** Tells the user whether an answer came from the model alone or used tools / external data. */
export function SourceBadge({ message }: { message: Pick<UiMessage, 'source' | 'tools_used'> }) {
  if (message.source === 'tool') {
    const names = message.tools_used.map(humanize).join(', ')
    return (
      <Badge tone="accent" title={names ? `Used: ${names}` : 'Used tools'}>
        <Wrench className="size-3" aria-hidden /> Used {message.tools_used.length > 1 ? `${message.tools_used.length} tools` : names || 'a tool'}
      </Badge>
    )
  }
  return <Badge>AI answer</Badge>
}
