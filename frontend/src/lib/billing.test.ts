import { describe, expect, it } from 'vitest'
import { renewalLine, usageFraction, usageLine } from './billing'
import type { BillingStatus } from '@/api/types'

const base: BillingStatus = { plan: 'plus', status: 'active', billing_period: 'monthly', renews_at: '2026-12-22T10:00:00Z', cancel_at_cycle_end: false, messages_today: 0, messages_limit: null, calls_today: 0, calls_limit: null }

describe('usage', () => {
  it('shows used of limit, never above the limit', () => {
    expect(usageLine(12, 25, 'messages')).toBe('12 of 25 messages used today')
    expect(usageLine(30, 25, 'messages')).toBe('25 of 25 messages used today')
  })
  it('is unlimited without a limit', () => {
    expect(usageLine(99, null, 'live calls')).toBe('Unlimited live calls')
    expect(usageFraction(99, null)).toBe(0)
  })
  it('fills a bar between 0 and 1', () => {
    expect(usageFraction(5, 20)).toBe(0.25)
    expect(usageFraction(50, 20)).toBe(1)
  })
})

describe('renewalLine', () => {
  it('says when Plus renews or ends', () => {
    expect(renewalLine(base)).toMatch(/^Renews on 22 December 2026$/)
    expect(renewalLine({ ...base, cancel_at_cycle_end: true })).toMatch(/^Ends on 22 December 2026\. It will not renew\.$/)
  })
  it('says nothing on the free plan', () => {
    expect(renewalLine({ ...base, plan: 'free', renews_at: null })).toBeNull()
  })
})
