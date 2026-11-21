import { describe, expect, it } from 'vitest'
import { formatIST, formatNextAvailable, formatSlotDate, formatSlotTime, istDate, istDateKey, istDayMonth, istTime, relativeDayIST } from './time'

describe('Asia/Kolkata formatting', () => {
  it('shows the IST wall-clock time of a UTC instant (UTC+5:30)', () => {
    expect(istTime('2026-11-23T04:30:00Z')).toBe('10:00 am')
    expect(istTime('2026-11-23T09:50:00Z')).toBe('3:20 pm')
    expect(istTime('2026-11-23T18:30:00Z')).toBe('12:00 am') // midnight in India
  })

  it('always labels the time as IST', () => {
    const s = formatIST('2026-11-23T04:30:00Z')
    expect(s).toContain('10:00 am')
    expect(s.endsWith('IST')).toBe(true)
    expect(s).toContain('23 Nov 2026')
    expect(s).toMatch(/Mon/)
  })

  it('does not depend on the browser timezone: the date rolls over at IST midnight', () => {
    // 19:00Z on the 22nd is 00:30 on the 23rd in India
    expect(istDateKey('2026-11-22T19:00:00Z')).toBe('2026-11-23')
    expect(istDate('2026-11-22T19:00:00Z')).toContain('23 Nov')
    expect(istDateKey('2026-11-22T18:29:00Z')).toBe('2026-11-22')
  })

  it('gives calendar-badge parts in IST', () => {
    expect(istDayMonth('2026-11-22T19:00:00Z')).toEqual({ day: '23', month: 'Nov' })
    expect(istDayMonth('2026-11-22T18:00:00Z')).toEqual({ day: '22', month: 'Nov' })
  })

  it('labels today / tomorrow / yesterday in IST', () => {
    const now = new Date('2026-11-23T20:00:00Z') // 01:30 on the 24th in India
    expect(relativeDayIST('2026-11-24T05:00:00Z', now)).toBe('Today')
    expect(relativeDayIST('2026-11-25T05:00:00Z', now)).toBe('Tomorrow')
    expect(relativeDayIST('2026-11-23T05:00:00Z', now)).toBe('Yesterday')
    expect(relativeDayIST('2026-12-30T05:00:00Z', now)).toBeNull()
  })
})

describe('slot helpers', () => {
  it('formats slot dates without timezone drift', () => {
    expect(formatSlotDate('2026-11-23')).toBe('Mon, 23 Nov')
    expect(formatSlotDate('2026-12-01')).toBe('Tue, 1 Dec')
    expect(formatSlotDate('garbage')).toBe('garbage')
  })

  it('converts 24 h slot times to 12 h', () => {
    expect(formatSlotTime('10:20')).toBe('10:20 am')
    expect(formatSlotTime('00:40')).toBe('12:40 am')
    expect(formatSlotTime('12:00')).toBe('12:00 pm')
    expect(formatSlotTime('14:05')).toBe('2:05 pm')
    expect(formatSlotTime('... (+4 more)')).toBe('... (+4 more)')
  })

  it('describes the next available slot', () => {
    expect(formatNextAvailable({ date: '2026-11-23', time: '10:00' })).toBe('Mon, 23 Nov, 10:00 am IST')
    expect(formatNextAvailable(null)).toBe('No free slot soon')
  })
})
