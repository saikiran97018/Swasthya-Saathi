import type { VaccineItem } from '@/api/types'

/** "21 Feb 2026" from a date-only string, without a time zone shift. */
export function fmtVaccineDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  if (!y || !m || !d) return iso
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
}

export function statusLabel(i: Pick<VaccineItem, 'status'>): string {
  return { given: 'Done', overdue: 'Overdue', due: 'Due now', upcoming: 'Coming up' }[i.status]
}
