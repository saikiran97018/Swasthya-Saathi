import { Link } from 'react-router-dom'
import { ArrowRight, BellRing, CalendarDays, Heart, Languages, MapPinned, MessageSquare, MessageSquareText, Phone, Siren, Users, Zap, type LucideIcon } from 'lucide-react'
import { useAppointments, useDashboard, useMe } from '@/api/hooks'
import { DoctorIllustration } from '@/components/health/DoctorIllustration'
import { LanguageChips } from '@/components/health/LanguageChips'
import { ConfirmationBadge } from '@/components/health/shared'
import { OPEN_NOTIFICATIONS_EVENT } from '@/components/health/NotificationBell'
import { UrgentHelpCard } from '@/components/health/UrgentHelpCard'
import { Button, Skeleton } from '@/components/ui/primitives'
import { cn } from '@/lib/format'
import { istDayMonth, istTime, istWeekday } from '@/lib/time'

interface Feature {
  to: string
  icon: LucideIcon
  title: string
  text: string
}

const FEATURES: Feature[] = [
  { to: '/chat', icon: MessageSquareText, title: 'Check my symptoms', text: 'Tell the assistant what is wrong. It checks how urgent it is and what kind of doctor to see.' },
  { to: '/call', icon: Phone, title: 'Live voice call', text: 'Talk to the assistant hands-free, in real time, in 10 Indian languages. The reply is spoken aloud.' },
  { to: '/find-care', icon: MapPinned, title: 'Find clinics near me', text: 'Real hospitals and clinics around your town, with phone numbers and directions when listed.' },
  { to: '/appointments', icon: CalendarDays, title: 'Plan visits, get reminders', text: 'Save a visit and get reminders. Clinics here do not confirm online, so you call to confirm.' },
  { to: '/family', icon: Users, title: 'Care for your family', text: 'Save parents and children once, and plan visits for each of them.' },
  { to: '/sos', icon: Siren, title: 'Emergency help', text: 'Emergency numbers, first aid steps and your own contacts, one tap away.' },
]

const STEPS = [
  { n: '1', title: 'Tell us how you feel', text: 'Type or speak, in your language.' },
  { n: '2', title: 'We check how urgent it is', text: 'Emergency signs get you to 112 and 108 first.' },
  { n: '3', title: 'Plan your visit', text: 'Pick a clinic near you and save the visit.' },
]

export default function HomePage() {
  const { data: me } = useMe()
  const dashboard = useDashboard()
  const upcoming = useAppointments('upcoming')
  const next = upcoming.data?.items.find((a) => a.status === 'booked')
  const data = dashboard.data
  const firstName = me && !me.is_guest ? me.display_name.trim().split(/\s+/)[0] : null

  return (
    <div className="relative">
      <div className="relative mx-auto grid w-full max-w-[1180px] gap-5 px-4 pt-4 pb-4 md:px-6 md:pt-5 lg:grid-cols-[minmax(0,1.78fr)_minmax(0,1fr)]">
        {/* ============================================================ left column */}
        <div className="min-w-0 space-y-5">
          <section aria-labelledby="hero-h" className="relative overflow-hidden rounded-[1.5rem] bg-gradient-to-r from-[#e3f6f1] via-[#d9f0ed] to-[#c8e9e6] px-5 pt-6 dark:from-accent-soft dark:via-accent-soft dark:to-soft sm:px-8">
            <div className="flex items-end justify-between gap-2">
              <div className="min-w-0 flex-1 pb-6 sm:max-w-[30rem] sm:pb-8">
                <p className="text-xs font-bold tracking-wide text-accent-text uppercase">Swasthya Saathi</p>
                <h1 id="hero-h" className="mt-1.5 text-[1.6rem] leading-tight font-bold tracking-tight text-accent-text sm:text-[2rem] md:text-[2.25rem]">
                  Healthcare help, in your own language
                </h1>
                <p className="mt-3 text-sm leading-relaxed text-fg/85 sm:text-[15px]">
                  {firstName ? `Hi ${firstName}. ` : ''}Speak or type in English, Hindi, Telugu, Tamil and more. Check how urgent your symptoms are, find real clinics near you, and plan visits with reminders.
                </p>
                <div className="mt-4 flex flex-wrap gap-2.5">
                  <Link to="/chat" className="inline-flex min-h-11 items-center gap-2 rounded-full bg-accent px-5 text-[15px] font-semibold text-accent-fg shadow-sm transition hover:brightness-110 active:scale-95">
                    <MessageSquareText className="size-[18px]" aria-hidden /> Talk to the assistant
                  </Link>
                  <Link to="/find-care" className="inline-flex min-h-11 items-center gap-2 rounded-full border border-accent/40 bg-elev px-5 text-[15px] font-semibold text-accent-text transition hover:bg-soft active:scale-95">
                    <MapPinned className="size-[18px]" aria-hidden /> Find a doctor
                  </Link>
                  <Link to="/call" className="inline-flex min-h-11 items-center gap-2 rounded-full border border-accent/40 bg-elev px-5 text-[15px] font-semibold text-accent-text transition hover:bg-soft active:scale-95">
                    <Phone className="size-[18px]" aria-hidden /> Start a live call
                  </Link>
                </div>
              </div>
              <DoctorIllustration className="-mb-px hidden w-40 shrink-0 min-[420px]:block sm:w-56 md:w-60" />
            </div>
          </section>

          <section aria-labelledby="lang-h" className="space-y-2.5">
            <h2 id="lang-h" className="flex items-center gap-2 text-sm font-semibold"><Languages className="size-[18px] text-accent-text" aria-hidden /> Your Language</h2>
            <LanguageChips />
          </section>

          <section aria-labelledby="what-h" className="space-y-3">
            <h2 id="what-h" className="text-lg font-bold">What you can do</h2>
            <ul className="grid gap-3 sm:grid-cols-2">
              {FEATURES.map((f) => (
                <li key={f.to}>
                  <Link to={f.to} className="card group flex h-full items-start gap-3.5 p-4 transition hover:border-accent/50 active:scale-[0.99]">
                    <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent-text"><f.icon className="size-[22px]" aria-hidden /></span>
                    <span className="min-w-0">
                      <span className="flex items-center gap-1.5 font-bold">{f.title} <ArrowRight className="size-4 text-accent-text opacity-0 transition group-hover:opacity-100" aria-hidden /></span>
                      <span className="mt-1 block text-sm leading-snug text-muted">{f.text}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>

          <section aria-labelledby="how-h" className="space-y-3">
            <h2 id="how-h" className="text-lg font-bold">How it works</h2>
            <ol className="grid gap-3 sm:grid-cols-3">
              {STEPS.map((s) => (
                <li key={s.n} className="card flex items-start gap-3 p-4">
                  <span className="grid size-8 shrink-0 place-items-center rounded-full bg-accent text-sm font-bold text-accent-fg" aria-hidden>{s.n}</span>
                  <span className="min-w-0">
                    <span className="block font-bold">{s.title}</span>
                    <span className="mt-0.5 block text-sm leading-snug text-muted">{s.text}</span>
                  </span>
                </li>
              ))}
            </ol>
          </section>

          <p className="rounded-2xl border border-line bg-elev/70 px-4 py-3 text-xs leading-relaxed text-muted">
            Swasthya Saathi gives general guidance, not a diagnosis, and it never replaces a doctor. Clinic details come from OpenStreetMap and may be incomplete: please phone to confirm a visit. In an emergency call 112 or 108.
          </p>
        </div>

        {/* ============================================================ right column */}
        <div className="min-w-0 space-y-4">
          <section aria-labelledby="next-h" className="card p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h2 id="next-h" className="flex items-center gap-2.5 font-bold">
                <span className="grid size-9 place-items-center rounded-xl bg-accent-soft text-accent-text"><CalendarDays className="size-5" aria-hidden /></span>
                Upcoming Appointment
              </h2>
              <Link to="/appointments" className="inline-flex items-center gap-1 text-xs font-semibold text-accent-text hover:underline">View All <ArrowRight className="size-3.5" aria-hidden /></Link>
            </div>
            {upcoming.isLoading ? (
              <Skeleton className="h-24" />
            ) : upcoming.isError ? (
              <p className="text-sm text-danger" role="alert">Could not load your appointments.</p>
            ) : next ? (
              <Link to="/appointments" className="flex items-center gap-3.5 rounded-2xl transition hover:bg-soft/60">
                <span className="grid w-[4.25rem] shrink-0 place-items-center rounded-2xl bg-accent-soft py-2 text-accent-text">
                  <span className="text-[11px] font-bold uppercase">{istDayMonth(next.starts_at).month}</span>
                  <span className="text-[1.65rem] leading-none font-bold">{istDayMonth(next.starts_at).day}</span>
                  <span className="mt-0.5 text-[11px] font-medium">{istWeekday(next.starts_at)}</span>
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[15px] leading-snug font-bold break-words">Consultation with {next.provider.doctor_name ?? next.provider.name}</span>
                  <span className="mt-1 block text-sm text-muted">{istTime(next.starts_at)} – {istTime(next.ends_at)} IST</span>
                  <span className="mt-1.5 block"><ConfirmationBadge confirmed={next.clinic_confirmed !== false} /></span>
                </span>
              </Link>
            ) : (
              <div className="flex flex-col items-start gap-3 rounded-2xl bg-soft/60 p-3.5">
                <p className="text-sm text-muted">No upcoming appointment yet. Find a doctor and plan a visit that suits you.</p>
                <Link to="/find-care" className="inline-flex h-10 items-center gap-1.5 rounded-xl bg-accent px-4 text-sm font-semibold text-accent-fg hover:brightness-110">Find a doctor</Link>
              </div>
            )}
          </section>

          <UrgentHelpCard />

          <section aria-labelledby="qa-h" className="space-y-2.5">
            <h2 id="qa-h" className="flex items-center gap-2 text-sm font-bold"><Zap className="size-[18px] text-accent-text" aria-hidden /> Quick Access</h2>
            <div className="grid grid-cols-3 gap-2.5">
              {dashboard.isLoading || !data ? (
                [0, 1, 2].map((i) => <Skeleton key={i} className="h-28" />)
              ) : (
                <>
                  <Tile to="/appointments" icon={CalendarDays} value={data.appointments_total} label="Appointments" />
                  <Tile onClick={() => window.dispatchEvent(new Event(OPEN_NOTIFICATIONS_EVENT))} icon={BellRing} value={data.unread_notifications} label="Unread Reminders" />
                  <Tile to="/history" icon={MessageSquare} value={data.conversations} label="Conversations" />
                </>
              )}
            </div>
            {dashboard.isError && (
              <div role="alert" className="flex items-center justify-between gap-3 text-sm text-danger">Could not load your summary. <Button size="sm" onClick={() => void dashboard.refetch()}>Retry</Button></div>
            )}
          </section>
        </div>
      </div>

      <p className="relative mx-auto flex max-w-[1180px] items-center justify-end gap-1.5 px-6 pt-1 pb-6 text-xs font-semibold text-accent-text">
        Better Health. A Healthier You. <Heart className="size-4" aria-hidden />
      </p>
    </div>
  )
}

function Tile({ to, onClick, icon: Icon, value, label }: { to?: string; onClick?: () => void; icon: LucideIcon; value: number; label: string }) {
  const body = (
    <>
      <span className="mx-auto mb-2 grid size-10 place-items-center rounded-full bg-accent-soft text-accent-text"><Icon className="size-5" aria-hidden /></span>
      <span className="block text-2xl leading-none font-bold tabular-nums">{value}</span>
      <span className="mt-1 block text-[11px] leading-tight text-muted">{label}</span>
    </>
  )
  const cls = 'card block px-2 py-3.5 text-center transition hover:border-accent/50 active:scale-[0.98]'
  return to ? (
    <Link to={to} className={cls}>{body}</Link>
  ) : (
    <button type="button" onClick={onClick} className={cn(cls, 'w-full')}>{body}</button>
  )
}
