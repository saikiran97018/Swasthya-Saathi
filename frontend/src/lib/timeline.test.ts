import { describe, expect, it } from 'vitest'
import type { Appointment } from '@/api/types'
import { buildTimeline, people, personOf } from './timeline'

const a = (id: string, starts_at: string, over: Partial<Appointment> = {}) => ({ id, ref: `AP-${id}`, starts_at, status: 'booked', family_member: null, ...over }) as unknown as Appointment
const mother = { id: 'f1', name: 'Lakshmi', relation: 'parent' }

const list = [
  a('1', '2026-10-05T05:00:00Z', { status: 'completed' }),
  a('2', '2026-11-23T05:00:00Z', { family_member: mother }),
  a('3', '2026-11-02T05:00:00Z', { status: 'completed' }),
  a('4', '2026-11-10T05:00:00Z', { status: 'cancelled' }),
  a('5', '2026-12-01T05:00:00Z'),
]

describe('buildTimeline', () => {
  it('groups by month, newest first, and leaves out cancelled visits', () => {
    const t = buildTimeline(list, null)
    expect(t.map((g) => g.label)).toEqual(['December 2026', 'November 2026', 'October 2026'])
    expect(t[1]?.items.map((x) => x.id)).toEqual(['2', '3']) // the cancelled one (4) is gone
  })
  it('filters by person', () => {
    expect(buildTimeline(list, 'Lakshmi').flatMap((g) => g.items.map((x) => x.id))).toEqual(['2'])
    expect(buildTimeline(list, 'Me').flatMap((g) => g.items.map((x) => x.id))).toEqual(['5', '3', '1'])
  })
  it('uses the Indian calendar for the month', () => {
    // 20:00 UTC on 30 Nov is already 1 December in India
    expect(buildTimeline([a('9', '2026-11-30T20:00:00Z')], null)[0]?.label).toBe('December 2026')
  })
  it('is empty for nothing', () => {
    expect(buildTimeline([], null)).toEqual([])
  })
})

describe('people', () => {
  it('lists Me first, then family names, only those with visits', () => {
    expect(people(list)).toEqual(['Me', 'Lakshmi'])
    expect(people([a('2', '2026-11-23T05:00:00Z', { family_member: mother })])).toEqual(['Lakshmi'])
    expect(personOf(list[1]!)).toBe('Lakshmi')
  })
})
