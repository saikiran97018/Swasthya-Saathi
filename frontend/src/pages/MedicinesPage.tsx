import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Clock, Pill, Plus, Trash2, X } from 'lucide-react'
import { api } from '@/api/endpoints'
import type { MedicineReminder } from '@/api/types'
import { Button, EmptyState, PageHeader, Skeleton } from '@/components/ui/primitives'
import { useToast } from '@/components/ui/Toast'

const KEY = ['medicine-reminders'] as const
const DAYS = [7, 14, 30, 90, 180]
const MAX_TIMES = 4
const field = 'h-12 w-full rounded-2xl border border-line bg-bg/60 px-4 text-[15px] outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/25'

/** "08:00" -> "8:00 am" */
export const clock12 = (hhmm: string): string => {
  const [h = '0', m = '00'] = hhmm.split(':')
  const hour = Number(h)
  return `${hour % 12 === 0 ? 12 : hour % 12}:${m} ${hour < 12 ? 'am' : 'pm'}`
}

export default function MedicinesPage() {
  const toast = useToast()
  const qc = useQueryClient()
  const list = useQuery({ queryKey: KEY, queryFn: api.medicineReminders, staleTime: 10_000 })
  const [label, setLabel] = useState('')
  const [times, setTimes] = useState<string[]>(['08:00'])
  const [days, setDays] = useState(30)

  const add = useMutation({
    mutationFn: () => api.addMedicineReminder({ label: label.trim(), times: [...new Set(times.filter(Boolean))].sort(), days }),
    onSuccess: () => {
      toast.success('Reminder set. You will be reminded every day.')
      setLabel('')
      setTimes(['08:00'])
      void qc.invalidateQueries({ queryKey: KEY })
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not set the reminder'),
  })
  const stop = useMutation({
    mutationFn: (series: string) => api.stopMedicineReminder(series),
    onSuccess: () => {
      toast.success('Reminder stopped')
      void qc.invalidateQueries({ queryKey: KEY })
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not stop the reminder'),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (label.trim().length >= 2 && times.some(Boolean)) add.mutate()
  }
  const items: MedicineReminder[] = list.data ?? []

  return (
    <div className="mx-auto w-full max-w-2xl p-4 md:p-8">
      <PageHeader title="Medicine reminders" description="A reminder every day, on your phone and in the app." />

      <section className="card mb-5 p-5" aria-label="Your reminders">
        <h2 className="font-semibold">Your reminders</h2>
        {list.isLoading ? (
          <Skeleton className="mt-3 h-20" />
        ) : list.isError ? (
          <div role="alert" className="mt-3 flex items-center justify-between gap-3">
            <span className="text-sm text-danger">Could not load your reminders.</span>
            <Button size="sm" onClick={() => void list.refetch()}>Retry</Button>
          </div>
        ) : items.length === 0 ? (
          <EmptyState icon={<Pill className="size-6" />} title="No reminders yet">Add the medicine your doctor prescribed and when to take it.</EmptyState>
        ) : (
          <ul className="mt-3 divide-y divide-line">
            {items.map((r) => (
              <li key={r.series} className="flex items-start justify-between gap-3 py-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 font-medium break-words"><Pill className="size-4 shrink-0 text-accent-text" aria-hidden />{r.label}</div>
                  <p className="mt-1 flex flex-wrap items-center gap-x-3 text-sm text-muted">
                    <span className="inline-flex items-center gap-1"><Clock className="size-3.5" aria-hidden />{r.times.map(clock12).join(', ')}</span>
                    {r.ends_on && <span>until {new Date(`${r.ends_on}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}</span>}
                  </p>
                </div>
                <Button size="sm" variant="ghost" className="text-danger hover:bg-danger-soft" loading={stop.isPending && stop.variables === r.series} onClick={() => stop.mutate(r.series)} aria-label={`Stop the reminder for ${r.label}`}>
                  <Trash2 className="size-4" aria-hidden /> Stop
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <form className="card space-y-4 p-5" onSubmit={submit} aria-label="Add a reminder">
        <h2 className="font-semibold">Add a reminder</h2>
        <div>
          <label htmlFor="med-label" className="mb-1.5 block text-sm font-medium">What to take</label>
          <input id="med-label" value={label} maxLength={60} onChange={(e) => setLabel(e.target.value)} placeholder="For example: BP tablet" className={field} />
        </div>
        <fieldset>
          <legend className="mb-1.5 text-sm font-medium">At what times</legend>
          <div className="space-y-2">
            {times.map((t, i) => (
              <div key={i} className="flex items-center gap-2">
                <input type="time" value={t} aria-label={`Time ${i + 1}`} onChange={(e) => setTimes((cur) => cur.map((x, j) => (j === i ? e.target.value : x)))} className={field} />
                {times.length > 1 && (
                  <Button type="button" size="sm" variant="ghost" aria-label={`Remove time ${i + 1}`} onClick={() => setTimes((cur) => cur.filter((_, j) => j !== i))}><X className="size-4" aria-hidden /></Button>
                )}
              </div>
            ))}
          </div>
          {times.length < MAX_TIMES && (
            <Button type="button" size="sm" variant="ghost" className="mt-2" onClick={() => setTimes((cur) => [...cur, '20:00'])}><Plus className="size-4" aria-hidden /> Add another time</Button>
          )}
        </fieldset>
        <div>
          <label htmlFor="med-days" className="mb-1.5 block text-sm font-medium">For how long</label>
          <select id="med-days" value={days} onChange={(e) => setDays(Number(e.target.value))} className={field}>
            {DAYS.map((d) => <option key={d} value={d}>{d} days</option>)}
          </select>
        </div>
        <Button type="submit" variant="primary" loading={add.isPending} disabled={label.trim().length < 2 || !times.some(Boolean)}>Set reminder</Button>
        <p className="text-xs text-muted">
          Saathi never suggests medicines or doses. Only add what your doctor told you. To get the reminder on your phone, turn on notifications in <Link to="/settings" className="font-medium text-accent-text underline-offset-2 hover:underline">Settings</Link>. You can also just say it: "Remind me to take my BP tablet at 8."
        </p>
      </form>
    </div>
  )
}
