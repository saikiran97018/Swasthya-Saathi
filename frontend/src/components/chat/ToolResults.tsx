import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { CalendarCheck, MapPin, Siren } from 'lucide-react'
import type { ToolExecution } from '@/api/types'
import { CopyChip, Stars } from '@/components/health/shared'
import { Badge } from '@/components/ui/primitives'
import { cn, humanize, providerKindLabel } from '@/lib/format'
import { nativeName } from '@/lib/language'
import { formatNextAvailable, formatSlotDate, formatSlotTime } from '@/lib/time'

type Json = Record<string, unknown>
const obj = (v: unknown): Json => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Json) : {})
const arr = (v: unknown): Json[] => (Array.isArray(v) ? v.map(obj) : [])
const str = (v: unknown): string | undefined => (typeof v === 'string' && v ? v : undefined)

/**
 * A friendlier body for tool results we know the shape of. Returns null for anything else
 * (unknown tools, failures), in which case the generic card is all that is shown.
 */
export function richResult(tool: ToolExecution): ReactNode {
  if (!tool.result) return null
  const r = obj(tool.result)
  switch (tool.tool_name) {
    case 'assess_urgency':
      return tool.status === 'success' ? <UrgencyView r={r} /> : null
    case 'find_healthcare_providers':
      return tool.status === 'success' ? <ProviderList r={r} /> : null
    case 'check_availability':
      return tool.status === 'success' ? <SlotChips r={r} /> : null
    case 'book_appointment':
    case 'reschedule_appointment':
      return tool.status === 'success' ? <BookingSummary r={r} rescheduled={tool.tool_name === 'reschedule_appointment'} /> : null
    case 'list_appointments':
      return tool.status === 'success' ? <AppointmentList r={r} /> : null
    case 'cancel_appointment':
      return tool.status === 'success' ? <p className="text-sm">Appointment <strong>{str(r.reference)}</strong> was cancelled.</p> : null
    case 'schedule_follow_up':
      return tool.status === 'success' ? <p className="text-sm">Follow-up reminder set for <strong>{str(r.reminder_on)}</strong>{str(r.note) ? ` · ${str(r.note)}` : ''}</p> : null
    case 'record_feedback':
      return tool.status === 'success' && typeof r.rating === 'number' ? (
        <div className="flex items-center gap-2 text-sm"><Stars rating={r.rating} /> <span>Thank you for your feedback.</span></div>
      ) : null
    default:
      return null
  }
}

// ----------------------------------------------------------------------------------- urgency
const URGENCY = {
  emergency: { label: 'Emergency', tone: 'bg-danger text-white' },
  urgent: { label: 'See a doctor today', tone: 'bg-saffron text-black' },
  routine: { label: 'Routine', tone: 'bg-ok text-white dark:text-black' },
} as const

function UrgencyView({ r }: { r: Json }) {
  const key = (str(r.urgency) ?? 'routine') as keyof typeof URGENCY
  const u = URGENCY[key] ?? URGENCY.routine
  const specialty = str(r.suggested_specialty)
  const signs = Array.isArray(r.matched_signs) ? (r.matched_signs as unknown[]).filter((s): s is string => typeof s === 'string') : []
  const emergency = key === 'emergency'
  return (
    <div className={cn('space-y-2.5 rounded-xl p-3', emergency ? 'border-2 border-danger bg-danger-soft' : 'bg-elev/70')}>
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn('inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-semibold', u.tone)}>
          {emergency && <Siren className="size-4" aria-hidden />}
          {u.label}
        </span>
        {specialty && <Badge tone="accent">Suggested: {humanize(specialty)}</Badge>}
      </div>
      {str(r.advice) && <p className={cn('text-sm', emergency && 'font-medium')}>{str(r.advice)}</p>}
      {signs.length > 0 && <p className="text-xs text-muted">Because of: {signs.join(', ')}</p>}
      {emergency && (
        <Link to="/sos" className="inline-flex h-11 items-center gap-2 rounded-xl bg-danger px-5 text-base font-semibold text-white shadow-sm hover:brightness-110">
          <Siren className="size-5" aria-hidden /> Open emergency help (SOS)
        </Link>
      )}
      {str(r.disclaimer) && !emergency && <p className="text-[11px] text-muted">{str(r.disclaimer)}</p>}
    </div>
  )
}

// --------------------------------------------------------------------------------- providers
function ProviderList({ r }: { r: Json }) {
  const items = arr(r.results)
  if (!items.length) return <p className="text-sm text-muted">{str(r.note) ?? 'No matching providers.'}</p>
  const shown = items.slice(0, 4)
  return (
    <div className="space-y-2">
      <ul className="space-y-2">
        {shown.map((p) => {
          const next = obj(p.next_available)
          const nextSlot = str(next.date) && str(next.time) ? { date: str(next.date) as string, time: str(next.time) as string } : null
          return (
            <li key={str(p.code)} className="rounded-xl bg-elev/70 p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-medium">{str(p.name)}</div>
                  <div className="text-xs text-muted">
                    {[str(p.doctor), providerKindLabel(str(p.type)), str(p.city)].filter(Boolean).join(' · ')}
                  </div>
                </div>
                <div className="text-right text-sm font-semibold">{typeof p.fee_inr === 'number' ? `₹${p.fee_inr}` : ''}</div>
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <Badge tone={nextSlot ? 'ok' : 'neutral'}><CalendarCheck className="size-3" aria-hidden /> {formatNextAvailable(nextSlot)}</Badge>
                {p.teleconsultation === true && <Badge tone="accent">Video visits</Badge>}
                {p.accepts_ayushman === true && <Badge>Ayushman</Badge>}
                {p.is_demo_listing === true && <Badge tone="saffron">Demo listing</Badge>}
                {Array.isArray(p.languages) && <span className="text-xs text-muted">{(p.languages as string[]).map((c) => nativeName(c)).join(', ')}</span>}
              </div>
            </li>
          )
        })}
      </ul>
      {items.length > shown.length && <p className="text-xs text-muted">+{items.length - shown.length} more</p>}
      {str(r.note) && <p className="text-xs text-muted">{str(r.note)}</p>}
    </div>
  )
}

// ------------------------------------------------------------------------------------ slots
function SlotChips({ r }: { r: Json }) {
  const provider = obj(r.provider)
  const slots = obj(r.open_slots)
  const days = Object.entries(slots)
  if (!days.length) return <p className="text-sm text-muted">{str(r.note) ?? 'No open slots in this period.'}</p>
  return (
    <div className="space-y-2.5">
      <div className="text-sm">
        <span className="font-medium">{str(provider.name)}</span>
        <span className="text-muted"> · times in IST</span>
      </div>
      {days.map(([date, times]) => (
        <div key={date}>
          <div className="mb-1 text-xs font-medium text-muted">{formatSlotDate(date)}</div>
          <ul className="flex flex-wrap gap-1.5">
            {(Array.isArray(times) ? (times as unknown[]) : []).map((t) => {
              const text = String(t)
              const isTime = /^\d{1,2}:\d{2}$/.test(text)
              return (
                <li key={text} className={cn('rounded-lg px-2.5 py-1 text-sm', isTime ? 'bg-accent-soft font-medium text-accent-text' : 'text-xs text-muted')}>
                  {isTime ? formatSlotTime(text) : text}
                </li>
              )
            })}
          </ul>
        </div>
      ))}
    </div>
  )
}

// ------------------------------------------------------------------------------ appointments
function BookingSummary({ r, rescheduled }: { r: Json; rescheduled: boolean }) {
  const provider = obj(r.provider)
  const reminders = arr(r.reminders_scheduled)
  const when = str(r.when)
  return (
    <div className="space-y-3 rounded-xl border border-ok/40 bg-ok-soft/60 p-3.5" role="status" aria-label="Booking confirmed">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-semibold text-ok">{rescheduled ? 'Appointment rescheduled' : 'Appointment confirmed'}</div>
        {str(r.reference) && <CopyChip value={str(r.reference) as string} />}
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
        {when && (<><dt className="text-muted">When</dt><dd className="font-semibold">{when.includes('IST') ? when : `${when} IST`}</dd></>)}
        {str(provider.name) && (<><dt className="text-muted">Where</dt><dd className="min-w-0 break-words"><span className="font-medium">{str(provider.name)}</span>{str(provider.address) && <span className="flex items-start gap-1 text-muted"><MapPin className="mt-0.5 size-3.5 shrink-0" aria-hidden />{str(provider.address)}</span>}</dd></>)}
        {typeof r.fee_inr === 'number' && (<><dt className="text-muted">Fee</dt><dd>₹{r.fee_inr}</dd></>)}
      </dl>
      {reminders.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-medium tracking-wide text-muted uppercase">Reminders set</div>
          <ul className="space-y-0.5 text-sm">
            {reminders.map((m, i) => (
              <li key={i}>
                <span className="font-medium">{humanize(str(m.kind) ?? 'reminder')}</span>
                <span className="text-muted"> · {str(m.when)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {r.data_source_notice !== undefined && <p className="text-[11px] text-muted">{str(r.data_source_notice)}</p>}
    </div>
  )
}

function AppointmentList({ r }: { r: Json }) {
  const items = arr(r.appointments)
  if (!items.length) return <p className="text-sm text-muted">No appointments found.</p>
  return (
    <ul className="space-y-1.5">
      {items.map((a) => (
        <li key={str(a.reference)} className="flex flex-wrap items-center gap-2 rounded-xl bg-elev/70 px-3 py-2 text-sm">
          <CopyChip value={str(a.reference) ?? ''} />
          <span className="min-w-0 flex-1">
            <span className="font-medium">{str(obj(a.provider).name)}</span>
            <span className="text-muted"> · {str(a.when)}</span>
          </span>
          <Badge tone={a.status === 'booked' ? 'accent' : a.status === 'completed' ? 'ok' : 'neutral'}>{humanize(str(a.status) ?? '')}</Badge>
        </li>
      ))}
    </ul>
  )
}
