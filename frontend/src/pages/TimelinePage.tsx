import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { CalendarCheck, CheckCircle2, Pill } from 'lucide-react'
import { useAppointments } from '@/api/hooks'
import { Badge, Button, EmptyState, PageHeader, Skeleton, ToggleChip } from '@/components/ui/primitives'
import { istDate, istTime } from '@/lib/time'
import { buildTimeline, people, personOf } from '@/lib/timeline'

const STATUS: Record<string, { label: string; tone: 'ok' | 'accent' | 'saffron' }> = {
  booked: { label: 'Upcoming', tone: 'accent' },
  completed: { label: 'Done', tone: 'ok' },
}

/** Every visit, past and upcoming, in one place, for you or for one family member. */
export default function TimelinePage() {
  const upcoming = useAppointments('upcoming')
  const past = useAppointments('past')
  const [person, setPerson] = useState<string | null>(null)

  const all = useMemo(() => [...(upcoming.data?.items ?? []), ...(past.data?.items ?? [])], [upcoming.data, past.data])
  const who = useMemo(() => people(all), [all])
  const groups = useMemo(() => buildTimeline(all, person), [all, person])
  const loading = upcoming.isLoading || past.isLoading
  const failed = upcoming.isError || past.isError

  return (
    <div className="mx-auto w-full max-w-2xl p-4 md:p-8">
      <PageHeader title="Health timeline" description="Your visits, past and upcoming." />

      {who.length > 1 && (
        <div role="group" aria-label="Show visits for" className="mb-4 flex flex-wrap gap-2">
          <ToggleChip active={person === null} onClick={() => setPerson(null)}>Everyone</ToggleChip>
          {who.map((n) => <ToggleChip key={n} active={person === n} onClick={() => setPerson(n)}>{n}</ToggleChip>)}
        </div>
      )}

      {loading ? (
        <Skeleton className="h-48" />
      ) : failed ? (
        <div role="alert" className="card flex items-center justify-between gap-3 p-5">
          <span className="text-sm text-danger">Could not load your visits.</span>
          <Button size="sm" onClick={() => { void upcoming.refetch(); void past.refetch() }}>Retry</Button>
        </div>
      ) : groups.length === 0 ? (
        <EmptyState icon={<CalendarCheck className="size-6" />} title="No visits yet" action={<Link to="/find-care" className="font-semibold text-accent-text hover:underline">Find a doctor</Link>}>
          Your visits will appear here once you book one.
        </EmptyState>
      ) : (
        <div className="space-y-6">
          {groups.map((g) => (
            <section key={g.key} aria-label={g.label}>
              <h2 className="label-caps mb-2">{g.label}</h2>
              <ol className="relative space-y-3 border-l-2 border-line pl-5">
                {g.items.map((a) => {
                  const s = STATUS[a.status] ?? { label: a.status, tone: 'saffron' as const }
                  return (
                    <li key={a.id} className="relative">
                      <span aria-hidden className="absolute top-4 -left-[1.62rem] grid size-3 place-items-center rounded-full bg-accent ring-4 ring-bg" />
                      <Link to="/appointments" className="card block p-4 transition hover:border-accent/40">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="font-semibold">{a.provider.name}</span>
                          <Badge tone={s.tone}>{a.status === 'completed' && <CheckCircle2 className="size-3" aria-hidden />} {s.label}</Badge>
                        </div>
                        <p className="mt-1 text-sm text-muted">{istDate(a.starts_at)} · {istTime(a.starts_at)} IST · {personOf(a)}</p>
                        <p className="mt-1 text-sm break-words">{a.reason}</p>
                        {a.feedback_rating != null && <p className="mt-1 text-xs text-muted">Your rating: {a.feedback_rating} of 5</p>}
                      </Link>
                    </li>
                  )
                })}
              </ol>
            </section>
          ))}
        </div>
      )}

      <p className="mt-6 text-sm text-muted">
        <Pill className="mr-1 inline size-4" aria-hidden /> Your daily medicine reminders are under <Link to="/medicines" className="font-medium text-accent-text hover:underline">Medicines</Link>.
      </p>
    </div>
  )
}
