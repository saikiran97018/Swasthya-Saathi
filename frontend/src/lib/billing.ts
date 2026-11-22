import type { BillingStatus } from '@/api/types'

/** "12 of 25 messages used today", or "Unlimited" on Plus. */
export function usageLine(used: number, limit: number | null, noun: string): string {
  return limit === null ? `Unlimited ${noun}` : `${Math.min(used, limit)} of ${limit} ${noun} used today`
}

export function usageFraction(used: number, limit: number | null): number {
  return limit === null || limit <= 0 ? 0 : Math.min(1, used / limit)
}

export function renewalLine(s: BillingStatus): string | null {
  if (s.plan !== 'plus' || !s.renews_at) return null
  const date = new Date(s.renews_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'long', year: 'numeric' })
  return s.cancel_at_cycle_end ? `Ends on ${date}. It will not renew.` : `Renews on ${date}`
}
