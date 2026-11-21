import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CalendarClock, CalendarX, CheckCheck, MapPin, Phone, Video, BellRing, FlaskConical } from 'lucide-react'
import { useCancelAppointment, useDemoAppointmentAction, useHealth } from '@/api/hooks'
import type { Appointment } from '@/api/types'
import { Badge, Button, Dialog } from '@/components/ui/primitives'
import { useToast } from '@/components/ui/Toast'
import { useChat } from '@/hooks/ChatProvider'
import { appointmentPrompts } from '@/lib/notifications'
import { cn, humanize } from '@/lib/format'
import { forLabel } from '@/lib/family'
import { nativeName } from '@/lib/language'
import { istDate, istTime, relativeDayIST } from '@/lib/time'
import { ProviderAvatar } from './Avatars'
import { FeedbackForm } from './FeedbackForm'
import { placeAddress, telLinkFor } from '@/lib/places'
import { ConfirmationBadge, CopyChip, DemoListingBadge, ModeBadge, ReminderTimeline } from './shared'

const STATUS_TONE = { booked: 'accent', completed: 'ok', cancelled: 'neutral' } as const

/** Open the appointment's conversation (or a new chat) with text in the composer, ready to edit and send. */
export function useOpenWithDraft() {
  const navigate = useNavigate()
  const { startNew, setDraft } = useChat()
  return (conversationId: string | null, text: string) => {
    if (!conversationId) startNew()
    setDraft(text)
    navigate(conversationId ? `/chat/${conversationId}` : '/chat')
  }
}

export function AppointmentCard({ appointment: a }: { appointment: Appointment }) {
  const toast = useToast()
  const openWithDraft = useOpenWithDraft()
  const { data: health } = useHealth()
  const cancel = useCancelAppointment()
  const complete = useDemoAppointmentAction('complete')
  const remind = useDemoAppointmentAction('remind')
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [reason, setReason] = useState('')

  const booked = a.status === 'booked'
  const day = relativeDayIST(a.starts_at)
  const p = a.provider
  const demoHelpers = health?.demo_mode === true && booked
  const planned = booked && a.clinic_confirmed === false
  const callHref = telLinkFor(p.phone)
  const showFee = p.source !== 'openstreetmap' && p.fee_inr > 0

  const doCancel = () => {
    cancel.mutate(
      { id: a.id, reason: reason.trim() || undefined },
      {
        onSuccess: () => {
          setConfirmOpen(false)
          setReason('')
          toast.success(`Appointment ${a.ref} cancelled`)
        },
        onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not cancel the appointment'),
      },
    )
  }

  const demo = (kind: 'complete' | 'remind') => {
    const m = kind === 'complete' ? complete : remind
    m.mutate(a.id, {
      onSuccess: () => toast.success(kind === 'complete' ? 'Visit marked as done. A feedback request is on its way.' : 'Reminder sent. Check the bell.'),
      onError: (e) => toast.error(e instanceof Error ? e.message : 'Demo action failed'),
    })
  }

  return (
    <article className={cn('card p-4 md:p-5', !booked && 'opacity-95')} aria-label={`Appointment ${a.ref}`}>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={STATUS_TONE[a.status] ?? 'neutral'}>{humanize(a.status)}</Badge>
            {booked && a.clinic_confirmed !== undefined && <ConfirmationBadge confirmed={a.clinic_confirmed} />}
            <ModeBadge mode={a.mode} />
            {p.is_demo && <DemoListingBadge />}
          </div>
          <div className="mt-2.5 flex items-center gap-3">
            <ProviderAvatar provider={p} size={44} />
            <div className="min-w-0">
              <h3 className="text-lg leading-snug font-bold break-words">{p.doctor_name ?? p.name}</h3>
              <p className="text-sm text-muted">{[p.doctor_name ? p.name : null, p.specialties.map(humanize).join(', ')].filter(Boolean).join(' · ')}</p>
            </div>
          </div>
        </div>
        <CopyChip value={a.ref} />
      </header>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div>
          <div className="text-xs font-medium tracking-wide text-muted uppercase">When</div>
          <div className="mt-0.5 text-base font-semibold">
            {day && <span className="mr-1.5 text-accent-text">{day},</span>}
            {istDate(a.starts_at)}
          </div>
          <div className="text-sm">{istTime(a.starts_at)} – {istTime(a.ends_at)} <span className="font-medium text-muted">IST</span></div>
        </div>
        <div className="min-w-0 text-sm">
          <div className="text-xs font-medium tracking-wide text-muted uppercase">{a.mode === 'teleconsultation' ? 'Video visit' : 'Where'}</div>
          {a.mode === 'teleconsultation' ? (
            <p className="mt-0.5 flex items-center gap-1.5"><Video className="size-4 shrink-0 text-muted" aria-hidden /> Online. The clinic will share the link.</p>
          ) : (
            <p className="mt-0.5 flex items-start gap-1.5 break-words"><MapPin className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />{placeAddress(p) || p.city}</p>
          )}
          {p.phone && <a href={`tel:${p.phone.replace(/\s/g, '')}`} className="mt-1 inline-flex items-center gap-1.5 text-accent-text hover:underline"><Phone className="size-3.5" aria-hidden />{p.phone}</a>}
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
        <div><dt className="text-xs text-muted">Patient</dt><dd className="font-medium break-words">{a.patient_name}{forLabel(a.family_member) && <span className="block text-xs font-normal text-muted">{forLabel(a.family_member)}</span>}</dd></div>
        <div><dt className="text-xs text-muted">Mobile</dt><dd className="font-mono">{a.patient_mobile}</dd></div>
        {showFee && <div><dt className="text-xs text-muted">Fee</dt><dd className="font-medium">₹{p.fee_inr}{p.accepts_ayushman && <span className="ml-1 text-xs text-muted">· Ayushman</span>}</dd></div>}
        <div><dt className="text-xs text-muted">Language</dt><dd>{nativeName(a.language)}</dd></div>
        <div className="col-span-2 sm:col-span-4"><dt className="text-xs text-muted">Reason</dt><dd className="break-words">{a.reason}</dd></div>
      </dl>

      {planned && (
        <div className="mt-4 flex flex-wrap items-center gap-3 rounded-2xl bg-saffron-soft px-4 py-3 text-sm text-saffron-text" role="note">
          <p className="min-w-0 flex-1 basis-56 font-medium">This clinic has not confirmed this time. Call them to confirm.</p>
          {callHref && p.phone ? (
            <a href={callHref} className="inline-flex h-11 items-center gap-2 rounded-2xl bg-accent px-4 font-semibold text-accent-fg hover:brightness-110">
              <Phone className="size-4" aria-hidden /> Call to confirm
            </a>
          ) : (
            <span>No phone number is listed for this place.</span>
          )}
        </div>
      )}

      {a.reschedule_count > 0 && <p className="mt-2 text-xs text-muted">Rescheduled {a.reschedule_count} time{a.reschedule_count === 1 ? '' : 's'}</p>}

      {a.status === 'completed' && <div className="mt-4"><FeedbackForm appointment={a} /></div>}

      {a.reminders.length > 0 && (
        <div className="mt-4 border-t border-line pt-4">
          <div className="mb-2 flex items-center gap-1.5 text-xs font-medium tracking-wide text-muted uppercase"><BellRing className="size-3.5" aria-hidden /> Reminders</div>
          <ReminderTimeline reminders={a.reminders} />
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-4">
        {booked && (
          <>
            <Button size="sm" variant="secondary" onClick={() => openWithDraft(a.conversation_id, appointmentPrompts.reschedule(a.ref))}>
              <CalendarClock className="size-4" aria-hidden /> Reschedule with assistant
            </Button>
            <Button size="sm" variant="ghost" className="text-danger hover:bg-danger-soft" onClick={() => setConfirmOpen(true)}>
              <CalendarX className="size-4" aria-hidden /> Cancel
            </Button>
          </>
        )}
      </div>

      {demoHelpers && (
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl border border-dashed border-saffron/60 bg-saffron-soft/40 px-3 py-2" role="group" aria-label="Demo helpers">
          <Badge tone="saffron"><FlaskConical className="size-3" aria-hidden /> Demo</Badge>
          <Button size="sm" variant="secondary" loading={complete.isPending && complete.variables === a.id} onClick={() => demo('complete')}>
            <CheckCheck className="size-4" aria-hidden /> Simulate visit done
          </Button>
          <Button size="sm" variant="secondary" loading={remind.isPending && remind.variables === a.id} onClick={() => demo('remind')}>
            <BellRing className="size-4" aria-hidden /> Send reminder now
          </Button>
        </div>
      )}

      <Dialog
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title="Cancel this appointment?"
        footer={
          <>
            <Button data-autofocus onClick={() => setConfirmOpen(false)}>Keep it</Button>
            <Button variant="danger" loading={cancel.isPending} onClick={doCancel}>Cancel appointment</Button>
          </>
        }
      >
        <p>
          <strong className="text-fg">{p.name}</strong>, {istDate(a.starts_at)} at {istTime(a.starts_at)} IST ({a.ref}). Its reminders will be cancelled too.
        </p>
        <label htmlFor={`reason-${a.id}`} className="mt-4 mb-1.5 block text-sm font-medium text-fg">Reason (optional)</label>
        <input
          id={`reason-${a.id}`}
          value={reason}
          maxLength={300}
          onChange={(e) => setReason(e.target.value)}
          placeholder="For example: I feel better, or the time doesn't suit me"
          className="h-10 w-full rounded-xl border border-line bg-bg px-3 text-sm text-fg outline-none focus:border-accent focus:ring-2 focus:ring-accent/25"
        />
      </Dialog>
    </article>
  )
}
