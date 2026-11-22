import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, CircleAlert, Clock, Syringe } from 'lucide-react'
import { api } from '@/api/endpoints'
import { useFamily } from '@/api/hooks'
import type { VaccineItem } from '@/api/types'
import { Badge, Button, EmptyState, PageHeader, Skeleton, ToggleChip } from '@/components/ui/primitives'
import { useToast } from '@/components/ui/Toast'
import { fmtVaccineDate, statusLabel } from '@/lib/vaccines'

const TONE = { given: 'ok', overdue: 'danger', due: 'saffron', upcoming: 'accent' } as const

export default function VaccinesPage() {
  const toast = useToast()
  const qc = useQueryClient()
  const family = useFamily()
  const [memberId, setMemberId] = useState<string | null>(null)

  // Children first: anyone with a date of birth, then anyone listed as a child.
  const candidates = useMemo(() => (family.data ?? []).filter((m) => m.birth_date || m.relation === 'child'), [family.data])
  useEffect(() => {
    if (!memberId && candidates[0]) setMemberId(candidates[0].id)
  }, [candidates, memberId])

  const view = useQuery({ queryKey: ['vaccinations', memberId], queryFn: () => api.vaccinations(memberId as string), enabled: !!memberId, staleTime: 10_000 })
  const mark = useMutation({
    mutationFn: ({ key, on }: { key: string; on: string | null }) => api.markVaccination(memberId as string, key, on),
    onSuccess: (data, v) => {
      qc.setQueryData(['vaccinations', memberId], data)
      void qc.invalidateQueries({ queryKey: ['notifications'] })
      toast.success(v.on ? 'Marked as given' : 'Tick removed')
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not save that'),
  })
  const today = new Date().toISOString().slice(0, 10)
  const v = view.data

  return (
    <div className="mx-auto w-full max-w-2xl p-4 md:p-8">
      <PageHeader title="Child vaccines" description="Which vaccines are due, and when. Tick each visit as it is done." />

      {family.isLoading ? (
        <Skeleton className="h-40" />
      ) : candidates.length === 0 ? (
        <EmptyState icon={<Syringe className="size-6" />} title="No child added yet" action={<Link to="/family" className="font-semibold text-accent-text hover:underline">Add a child in Family</Link>}>
          Add your child with their date of birth and Saathi will show the vaccination schedule and remind you before each visit.
        </EmptyState>
      ) : (
        <>
          {candidates.length > 1 && (
            <div role="group" aria-label="Choose a child" className="mb-4 flex flex-wrap gap-2">
              {candidates.map((m) => <ToggleChip key={m.id} active={m.id === memberId} onClick={() => setMemberId(m.id)}>{m.name}</ToggleChip>)}
            </div>
          )}

          {view.isLoading ? (
            <Skeleton className="h-64" />
          ) : view.isError || !v ? (
            <div role="alert" className="card flex items-center justify-between gap-3 p-5">
              <span className="text-sm text-danger">Could not load the schedule.</span>
              <Button size="sm" onClick={() => void view.refetch()}>Retry</Button>
            </div>
          ) : !v.eligible ? (
            <EmptyState icon={<Syringe className="size-6" />} title={v.reason === 'too_old' ? 'The schedule is for children up to 16' : `Add ${v.name}'s date of birth`} action={<Link to="/family" className="font-semibold text-accent-text hover:underline">Open Family</Link>}>
              {v.reason === 'too_old' ? 'This person is past the childhood schedule.' : 'The vaccine dates are worked out from the exact date of birth.'}
            </EmptyState>
          ) : (
            <>
              <ol className="space-y-3" aria-label={`Vaccination schedule for ${v.name}`}>
                {v.items.map((i: VaccineItem) => (
                  <li key={i.key} className="card p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2 font-semibold">
                        {i.status === 'given' ? <CheckCircle2 className="size-5 text-ok" aria-hidden /> : i.status === 'overdue' ? <CircleAlert className="size-5 text-danger" aria-hidden /> : <Clock className="size-5 text-muted" aria-hidden />}
                        {i.label}
                      </div>
                      <Badge tone={TONE[i.status]}>{statusLabel(i)}</Badge>
                    </div>
                    <p className="mt-1 text-sm text-muted">{i.given_on ? `Given on ${fmtVaccineDate(i.given_on)}` : `Due ${fmtVaccineDate(i.due_on)}`}</p>
                    <p className="mt-1.5 text-sm break-words">{i.vaccines.join(' · ')}</p>
                    {i.note && <p className="mt-1 text-xs text-muted">{i.note}</p>}
                    <div className="mt-3">
                      {i.status === 'given' ? (
                        <Button size="sm" variant="ghost" loading={mark.isPending && mark.variables?.key === i.key} onClick={() => mark.mutate({ key: i.key, on: null })}>Undo</Button>
                      ) : (
                        <Button size="sm" variant={i.status === 'upcoming' ? 'secondary' : 'primary'} loading={mark.isPending && mark.variables?.key === i.key} onClick={() => mark.mutate({ key: i.key, on: today })}>Mark as given today</Button>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
              <p className="mt-4 text-xs text-muted">{v.disclaimer}</p>
              <p className="mt-2 text-sm"><Link to="/find-care" className="font-semibold text-accent-text hover:underline">Find a clinic or health centre</Link></p>
            </>
          )}
        </>
      )}
    </div>
  )
}
