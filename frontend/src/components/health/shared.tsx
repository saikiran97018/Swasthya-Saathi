import { useState } from 'react'
import { Check, Copy, Phone, Star, Video, Building2, FlaskConical } from 'lucide-react'
import type { ReminderInfo } from '@/api/types'
import { Badge } from '@/components/ui/primitives'
import { useToast } from '@/components/ui/Toast'
import { cn, humanize } from '@/lib/format'
import { formatIST } from '@/lib/time'

/** A reference code (AP-XXXXX) that can be copied with one tap. */
export function CopyChip({ value, label = 'Copy reference' }: { value: string; label?: string }) {
  const toast = useToast()
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      toast.error('Could not copy. Select the code and copy it manually.')
    }
  }
  return (
    <button
      type="button"
      onClick={copy}
      aria-label={`${label}: ${value}`}
      title={label}
      className="inline-flex items-center gap-1.5 rounded-lg bg-soft px-2.5 py-1 font-mono text-xs font-semibold tracking-wide transition hover:bg-line"
    >
      {value}
      {copied ? <Check className="size-3.5 text-ok" aria-hidden /> : <Copy className="size-3.5 text-muted" aria-hidden />}
    </button>
  )
}

export function Stars({ rating, className }: { rating: number; className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-0.5', className)} role="img" aria-label={`${rating} out of 5 stars`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <Star key={i} className={cn('size-4', i <= rating ? 'fill-saffron text-saffron' : 'text-line')} aria-hidden />
      ))}
    </span>
  )
}

export function ModeBadge({ mode }: { mode: string }) {
  return mode === 'teleconsultation' ? (
    <Badge tone="accent"><Video className="size-3" aria-hidden /> Video visit</Badge>
  ) : (
    <Badge><Building2 className="size-3" aria-hidden /> In person</Badge>
  )
}

/** Whether the clinic has confirmed the visit. A planned visit (false) still needs the person's own phone call. */
export function ConfirmationBadge({ confirmed }: { confirmed: boolean }) {
  return confirmed ? (
    <Badge tone="ok"><Check className="size-3" aria-hidden /> Confirmed</Badge>
  ) : (
    <Badge tone="saffron" title="The clinic has not confirmed this time. Call them to confirm.">
      <Phone className="size-3" aria-hidden /> Planned - call to confirm
    </Badge>
  )
}

export function DemoListingBadge() {
  return (
    <Badge tone="saffron" title="This listing is sample data for the demo, not a real clinic.">
      <FlaskConical className="size-3" aria-hidden /> Demo listing
    </Badge>
  )
}

const REMINDER_LABEL: Record<string, string> = { day_before: 'The day before', two_hours_before: '2 hours before', feedback: 'Feedback request', follow_up: 'Follow-up' }

/** When each reminder fires (IST) and whether it has already been delivered. */
export function ReminderTimeline({ reminders }: { reminders: ReminderInfo[] }) {
  if (!reminders.length) return null
  const sorted = [...reminders].sort((a, b) => new Date(a.due_at).getTime() - new Date(b.due_at).getTime())
  return (
    <ol className="space-y-1.5" aria-label="Reminders">
      {sorted.map((r, i) => {
        const delivered = r.status === 'delivered'
        const cancelled = r.status === 'cancelled'
        return (
          <li key={`${r.kind}-${i}`} className="flex items-center gap-2.5 text-sm">
            <span aria-hidden className={cn('size-2.5 shrink-0 rounded-full border-2', delivered ? 'border-ok bg-ok' : cancelled ? 'border-line bg-line' : 'border-accent bg-transparent')} />
            <span className={cn('min-w-0 flex-1', cancelled && 'text-muted line-through')}>
              <span className="font-medium">{REMINDER_LABEL[r.kind] ?? humanize(r.kind)}</span>
              <span className="text-muted"> · {formatIST(r.due_at)}</span>
            </span>
            <Badge tone={delivered ? 'ok' : cancelled ? 'neutral' : 'accent'}>{delivered ? 'Sent' : cancelled ? 'Cancelled' : 'Scheduled'}</Badge>
          </li>
        )
      })}
    </ol>
  )
}
