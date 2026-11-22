import { useState } from 'react'
import { ThumbsDown, ThumbsUp } from 'lucide-react'
import { api } from '@/api/endpoints'
import type { ReplyRating as Rating, ReplyReason } from '@/api/types'
import { IconButton } from '@/components/ui/primitives'
import { useToast } from '@/components/ui/Toast'
import { cn } from '@/lib/format'

export const REPLY_REASONS: { value: ReplyReason; label: string }[] = [
  { value: 'wrong_info', label: 'Wrong information' },
  { value: 'misunderstood', label: 'Did not understand me' },
  { value: 'unsafe', label: 'Unsafe advice' },
  { value: 'not_helpful', label: 'Not helpful' },
  { value: 'other', label: 'Something else' },
]

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** Thumbs up / down on one reply. A thumbs-down asks why, so wrong answers can be found and fixed. */
export function ReplyRating({ messageId }: { messageId: string }) {
  const toast = useToast()
  const [rating, setRating] = useState<Rating | null>(null)
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)

  if (!UUID.test(messageId)) return null // a reply that is still being saved has no id yet

  const send = async (next: Rating, reason?: ReplyReason) => {
    setBusy(true)
    try {
      await api.rateReply(messageId, { rating: next, ...(reason && { reason }) })
      setRating(next)
      setAsking(false)
      toast.success(next === 'up' ? 'Thanks for the feedback' : 'Thanks. We will look at this answer.')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save your feedback')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-0.5">
      <IconButton label="Good reply" size="sm" disabled={busy} aria-pressed={rating === 'up'} onClick={() => void send('up')}>
        <ThumbsUp className={cn('size-4', rating === 'up' && 'fill-current text-ok')} />
      </IconButton>
      <IconButton label="Bad reply" size="sm" disabled={busy} aria-pressed={rating === 'down'} onClick={() => setAsking((a) => !a)}>
        <ThumbsDown className={cn('size-4', rating === 'down' && 'fill-current text-danger')} />
      </IconButton>
      {asking && (
        <div role="group" aria-label="What was wrong?" className="flex w-full flex-wrap gap-1.5 pt-1.5">
          {REPLY_REASONS.map((r) => (
            <button
              key={r.value}
              type="button"
              disabled={busy}
              onClick={() => void send('down', r.value)}
              className="min-h-9 rounded-full border border-line bg-elev px-3 text-xs font-medium hover:bg-soft disabled:opacity-50"
            >
              {r.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
