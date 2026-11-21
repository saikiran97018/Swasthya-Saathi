import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { BellRing, CalendarDays, CalendarHeart, CalendarPlus, Check, MapPin, Phone, Search, Sparkles, Video } from 'lucide-react'
import { useAppointments, useChecklist, useNotifications, usePlannedRefs, useUpdateTask } from '@/api/hooks'
import type { Appointment, Task } from '@/api/types'
import { AppointmentCard, useOpenWithDraft } from '@/components/health/AppointmentCard'
import { ProviderAvatar } from '@/components/health/Avatars'
import { FeedbackForm } from '@/components/health/FeedbackForm'
import { ConfirmationBadge, ReminderTimeline } from '@/components/health/shared'
import { UrgentHelpCard } from '@/components/health/UrgentHelpCard'
import { Badge, Button, EmptyState, ProgressBar, SectionLabel, Segmented, Skeleton } from '@/components/ui/primitives'
import { useToast } from '@/components/ui/Toast'
import { appointmentToIcs, downloadTextFile } from '@/lib/ics'
import { countdownLabel } from '@/lib/countdown'
import { cn, humanize, relativeTime } from '@/lib/format'
import { placeAddress, telLinkFor } from '@/lib/places'
import { istDate, istTime, relativeDayIST } from '@/lib/time'

type Tab = 'upcoming' | 'past'

const CHECKLIST_PROMPT = 'Please make a checklist of what I should prepare before my doctor appointment.'

export default function AppointmentsPage() {
  const [tab, setTab] = useState<Tab>('upcoming')
  const openWithDraft = useOpenWithDraft()
  const list = useAppointments(tab)
  const upcoming = useAppointments('upcoming')
  const past = useAppointments('past')
  const items = list.data?.items ?? []

  const next = upcoming.data?.items.find((a) => a.status === 'booked')
  const toRate = past.data?.items.find((a) => a.status === 'completed' && a.feedback_rating === null)

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-5 md:px-8 md:py-8">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[1.65rem] leading-tight font-bold tracking-tight md:text-3xl">Care plan</h1>
          <p className="mt-1.5 text-muted">Your next visit, what to prepare and your follow-ups. Times are in Indian Standard Time (IST).</p>
        </div>
        <Link to="/find-care" className="inline-flex h-11 items-center gap-2 rounded-2xl bg-accent px-4 text-sm font-semibold text-accent-fg shadow-sm transition hover:brightness-110">
          <Search className="size-4" aria-hidden /> Book an appointment
        </Link>
      </header>

      <div className="grid gap-5 lg:grid-cols-5">
        {/* ------------------------------------------------------------ main column */}
        <div className="space-y-5 lg:col-span-3">
          {upcoming.isLoading ? <Skeleton className="h-52" /> : next ? <NextAppointmentHero appointment={next} /> : null}

          <section aria-label="Appointments">
            <div className="mb-3 flex items-center justify-between gap-3">
              <SectionLabel>Appointments</SectionLabel>
              <Segmented<Tab> label="Appointments" value={tab} onChange={setTab} options={[{ value: 'upcoming', label: 'Upcoming' }, { value: 'past', label: 'Past' }]} />
            </div>
            {list.isLoading ? (
              <div className="space-y-4" aria-busy>{[0, 1].map((i) => <Skeleton key={i} className="h-64" />)}</div>
            ) : list.isError ? (
              <div role="alert" className="card flex items-center justify-between gap-3 p-4">
                <span className="text-sm text-danger">{list.error instanceof Error ? list.error.message : 'Could not load your appointments.'}</span>
                <Button size="sm" onClick={() => void list.refetch()}>Retry</Button>
              </div>
            ) : items.length === 0 ? (
              <div className="card">
                <EmptyState
                  icon={<CalendarHeart className="size-6" />}
                  title={tab === 'upcoming' ? 'No upcoming appointments' : 'No past appointments yet'}
                  action={tab === 'upcoming' ? <Link to="/find-care" className="inline-flex h-12 items-center rounded-2xl bg-accent px-5 font-semibold text-accent-fg">Find a doctor</Link> : undefined}
                >
                  {tab === 'upcoming' ? 'Pick a doctor and a time that suits you.' : 'Completed and cancelled visits will be listed here.'}
                </EmptyState>
              </div>
            ) : (
              <ul className="space-y-4">
                {items.map((a) => (
                  <li key={a.id}><AppointmentCard appointment={a} /></li>
                ))}
              </ul>
            )}
          </section>
        </div>

        {/* ------------------------------------------------------------ side column */}
        <div className="space-y-5 lg:col-span-2">
          <Checklist onAsk={() => openWithDraft(null, CHECKLIST_PROMPT)} />
          <FollowUps next={next} />
          {toRate && (
            <section aria-labelledby="fb-h" className="card p-4">
              <SectionLabel id="fb-h" className="mb-2.5">Visit feedback</SectionLabel>
              <p className="mb-3 text-sm text-muted">{toRate.provider.doctor_name ?? toRate.provider.name} · {istDate(toRate.starts_at)}</p>
              <FeedbackForm appointment={toRate} />
            </section>
          )}
          <UrgentHelpCard />
        </div>
      </div>
    </div>
  )
}

function NextAppointmentHero({ appointment: a }: { appointment: Appointment }) {
  const toast = useToast()
  const p = a.provider
  const tele = a.mode === 'teleconsultation'
  const day = relativeDayIST(a.starts_at)
  const planned = a.clinic_confirmed === false
  const callHref = telLinkFor(p.phone)

  const addToCalendar = () => {
    try {
      downloadTextFile(`appointment-${a.ref}.ics`, appointmentToIcs(a))
      toast.success('Calendar file downloaded. Open it to add the visit to your calendar.')
    } catch {
      toast.error('Could not create the calendar file.')
    }
  }

  return (
    <section aria-labelledby="next-h" className="bg-hero relative overflow-hidden rounded-[1.5rem] p-5 text-white shadow-[var(--shadow-pop)]">
      <div aria-hidden className="absolute -top-16 -right-10 size-56 rounded-full bg-white/10 blur-2xl" />
      <div className="relative">
        <div className="flex items-center justify-between gap-3">
          <h2 id="next-h" className="text-[11px] font-bold tracking-[0.08em] text-white/80 uppercase">Next appointment</h2>
          <span className="rounded-full bg-white/18 px-3 py-1 text-xs font-bold">{countdownLabel(a.starts_at)}</span>
        </div>

        <div className="mt-3 flex items-center gap-3.5">
          <ProviderAvatar provider={p} size={60} className="ring-2 ring-white/40" />
          <div className="min-w-0">
            <p className="text-xl leading-snug font-bold break-words">{p.doctor_name ?? p.name}</p>
            <p className="text-sm text-white/80">{[p.doctor_name ? p.name : null, p.specialties.map(humanize).join(', ')].filter(Boolean).join(' · ')}</p>
          </div>
        </div>

        {a.clinic_confirmed !== undefined && <div className="mt-3"><ConfirmationBadge confirmed={a.clinic_confirmed} /></div>}

        <dl className="mt-4 space-y-2 text-[15px]">
          <div className="flex items-center gap-2.5">
            <CalendarDays className="size-5 shrink-0 text-white/80" aria-hidden />
            <div><dt className="sr-only">When</dt><dd className="font-semibold">{day ? `${day}, ` : ''}{istDate(a.starts_at)} · {istTime(a.starts_at)} IST</dd></div>
          </div>
          <div className="flex items-start gap-2.5">
            {tele ? <Video className="mt-0.5 size-5 shrink-0 text-white/80" aria-hidden /> : <MapPin className="mt-0.5 size-5 shrink-0 text-white/80" aria-hidden />}
            <div className="min-w-0"><dt className="sr-only">Where</dt><dd className="break-words">{tele ? 'Video visit (online). The clinic will share the link.' : placeAddress(p) || p.city}</dd></div>
          </div>
        </dl>

        <div className="mt-5 flex flex-wrap items-center gap-2.5">
          <button onClick={addToCalendar} className="inline-flex h-12 items-center gap-2 rounded-2xl bg-white px-5 text-[15px] font-semibold text-[#0b5750] transition active:scale-[0.98] hover:bg-white/90">
            <CalendarPlus className="size-5" aria-hidden /> Add to calendar
          </button>
          {planned && callHref && (
            <a href={callHref} className="inline-flex h-12 items-center gap-2 rounded-2xl border-2 border-white/70 px-5 text-[15px] font-semibold text-white transition hover:bg-white/10">
              <Phone className="size-5" aria-hidden /> Call to confirm
            </a>
          )}
          <span className="font-mono text-xs font-semibold tracking-wide text-white/80">{a.ref}</span>
          {p.is_demo && <span className="rounded-full bg-white/18 px-2.5 py-1 text-xs font-medium">Demo listing</span>}
        </div>
      </div>
    </section>
  )
}

function Checklist({ onAsk }: { onAsk: () => void }) {
  const { data, isLoading, isError, refetch } = useChecklist()
  const update = useUpdateTask()
  const toast = useToast()
  const tasks = useMemo(() => (data?.items ?? []).filter((t) => t.status !== 'cancelled'), [data])
  const done = tasks.filter((t) => t.status === 'done').length
  const pct = tasks.length ? (done / tasks.length) * 100 : 0

  const toggle = (t: Task) =>
    update.mutate({ id: t.id, status: t.status === 'done' ? 'open' : 'done' }, { onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not update that item') })

  return (
    <section aria-labelledby="chk-h" className="card p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <SectionLabel id="chk-h">Pre-visit checklist</SectionLabel>
        {tasks.length > 0 && <span className="text-xs font-semibold text-muted tabular-nums">{done} of {tasks.length} done</span>}
      </div>
      {isLoading ? (
        <Skeleton className="h-24" />
      ) : isError ? (
        <div role="alert" className="flex items-center justify-between gap-3 text-sm text-danger">Could not load your checklist. <Button size="sm" onClick={() => void refetch()}>Retry</Button></div>
      ) : tasks.length === 0 ? (
        <div className="flex flex-col items-start gap-3">
          <p className="text-sm text-muted">Nothing here yet. Ask the assistant what to prepare, and it will add items you can tick off.</p>
          <Button size="sm" variant="soft" onClick={onAsk}><Sparkles className="size-4" aria-hidden /> Ask the assistant</Button>
        </div>
      ) : (
        <>
          <ProgressBar value={pct} label="Checklist progress" className="mb-3" />
          <ul className="-mx-1.5">
            {tasks.map((t) => {
              const checked = t.status === 'done'
              return (
                <li key={t.id}>
                  <button
                    type="button"
                    role="checkbox"
                    aria-checked={checked}
                    onClick={() => toggle(t)}
                    className="flex min-h-12 w-full items-start gap-3 rounded-xl px-1.5 py-2.5 text-left transition hover:bg-soft"
                  >
                    <span className={cn('mt-0.5 grid size-6 shrink-0 place-items-center rounded-lg border-2 transition', checked ? 'border-accent bg-accent text-accent-fg' : 'border-line bg-elev')}>
                      {checked && <Check className="size-4" aria-hidden />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className={cn('block font-medium break-words', checked && 'text-muted line-through')}>{t.title}</span>
                      {t.description && <span className="block text-sm break-words text-muted">{t.description}</span>}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </section>
  )
}

const KIND_LABEL: Record<string, string> = { follow_up: 'Follow-up', appointment_reminder: 'Reminder', feedback_request: 'Feedback' }

function FollowUps({ next }: { next: Appointment | undefined }) {
  const { data, isLoading } = useNotifications()
  const planned = usePlannedRefs()
  const items = (data?.items ?? []).filter((n) => n.kind === 'follow_up' || n.kind === 'appointment_reminder' || n.kind === 'feedback_request').slice(0, 5)
  const scheduled = next?.reminders.filter((r) => r.status !== 'cancelled') ?? []

  return (
    <section aria-labelledby="fu-h" className="card p-4">
      <SectionLabel id="fu-h" className="mb-3">Follow-ups & reminders</SectionLabel>
      {isLoading ? (
        <Skeleton className="h-20" />
      ) : items.length === 0 && scheduled.length === 0 ? (
        <div className="flex items-center gap-3 text-sm text-muted">
          <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent-text"><BellRing className="size-5" aria-hidden /></span>
          Reminders and follow-ups for your visits will appear here.
        </div>
      ) : (
        <div className="space-y-4">
          {scheduled.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-semibold text-muted">For your next visit</p>
              <ReminderTimeline reminders={scheduled} />
            </div>
          )}
          {items.length > 0 && (
            <ul className="divide-y divide-line">
              {items.map((n) => (
                <li key={n.id} className="flex items-start gap-3 py-2.5 first:pt-0 last:pb-0">
                  <span className={cn('mt-1.5 size-2.5 shrink-0 rounded-full', n.read_at ? 'bg-line' : 'bg-accent')} aria-hidden />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-sm font-semibold break-words">{n.title}</span>
                      <Badge tone={n.kind === 'follow_up' ? 'accent' : 'neutral'}>{KIND_LABEL[n.kind] ?? humanize(n.kind)}</Badge>
                      {n.appointment_ref && planned.has(n.appointment_ref) && <ConfirmationBadge confirmed={false} />}
                    </div>
                    <p className="mt-0.5 text-sm break-words text-muted">{n.message}</p>
                    <p className="mt-0.5 text-xs text-muted">{relativeTime(n.delivered_at)}{n.read_at ? '' : ' · New'}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}

