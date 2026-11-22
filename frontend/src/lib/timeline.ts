import type { Appointment } from '@/api/types'

export interface TimelineGroup {
  key: string // YYYY-MM
  label: string // "November 2026"
  items: Appointment[]
}

/** Who a visit was for: the family member's name, or 'Me' for the account holder. */
export const personOf = (a: Pick<Appointment, 'family_member'>): string => a.family_member?.name ?? 'Me'

export function people(list: Appointment[]): string[] {
  const names = new Set(list.map(personOf))
  return ['Me', ...[...names].filter((n) => n !== 'Me').sort((x, y) => x.localeCompare(y))].filter((n) => names.has(n))
}

const monthKey = (iso: string) => new Date(iso).toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' }).slice(0, 7)
const monthLabel = (iso: string) => new Date(iso).toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', month: 'long', year: 'numeric' })

/** All visits, newest first, grouped by month, optionally for one person. Cancelled visits are left out. */
export function buildTimeline(list: Appointment[], person: string | null): TimelineGroup[] {
  const shown = list.filter((a) => a.status !== 'cancelled' && (!person || personOf(a) === person)).sort((x, y) => new Date(y.starts_at).getTime() - new Date(x.starts_at).getTime())
  const groups: TimelineGroup[] = []
  for (const a of shown) {
    const key = monthKey(a.starts_at)
    const last = groups[groups.length - 1]
    if (last && last.key === key) last.items.push(a)
    else groups.push({ key, label: monthLabel(a.starts_at), items: [a] })
  }
  return groups
}
