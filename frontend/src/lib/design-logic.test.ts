import { describe, expect, it } from 'vitest'
import type { Appointment } from '@/api/types'
import { avatarDataUri, initials } from './avatar'
import { bookingPayload, describeBookingError, normalizeMobile, validateBooking, type BookingForm } from './booking'
import { appointmentToIcs, buildIcs, escapeIcsText, foldLine, icsDate } from './ics'
import { ratingLabel } from './rating'
import { dayOptions, groupSlotsByPeriod, periodOf, slotParam } from './slots'
import { clampLevel, composeTriageMessage, discomfortLabel, exampleFor, MAX_FREE_TEXT, SYMPTOM_CHIPS } from './symptoms'

describe('symptom message composer', () => {
  it('returns nothing until there is something to assess', () => {
    expect(composeTriageMessage({ chips: [], text: '   ', level: 4 })).toBe('')
  })

  it('combines chips, free text and the discomfort level into one English message', () => {
    const m = composeTriageMessage({ chips: ['fever', 'cough'], text: '  since   two days ', level: 6 })
    expect(m).toContain('Symptoms: fever and chills and a persistent cough.')
    expect(m).toContain('In my own words: since two days')
    expect(m).toContain('Discomfort level: 6/10 (moderate).')
    expect(m.startsWith('Please check how urgent my symptoms are')).toBe(true)
  })

  it('lists three or more symptoms with commas and handles "general consultation" separately', () => {
    const m = composeTriageMessage({ chips: ['fever', 'cough', 'rash', 'general'], text: '', level: 2 })
    expect(m).toContain('Symptoms: fever and chills, a persistent cough and a skin rash.')
    expect(m).toContain('I would also like a general consultation.')
    expect(m).toContain('(mild)')
  })

  it('works with free text alone and ignores unknown chip ids', () => {
    const m = composeTriageMessage({ chips: ['nonsense'], text: 'my knee hurts', level: 9 })
    expect(m).toContain('In my own words: my knee hurts')
    expect(m).not.toContain('Symptoms:')
    expect(m).toContain('(urgent)')
  })

  it('caps very long free text and clamps the level', () => {
    const m = composeTriageMessage({ chips: [], text: 'x'.repeat(5000), level: 99 })
    expect(m).toContain('x'.repeat(MAX_FREE_TEXT))
    expect(m).not.toContain('x'.repeat(MAX_FREE_TEXT + 1))
    expect(m).toContain('10/10')
    expect(clampLevel(-3)).toBe(1)
    expect(clampLevel(Number.NaN)).toBe(4)
    expect(clampLevel(4.6)).toBe(5)
  })

  it('leaves the discomfort level out unless it was set', () => {
    expect(composeTriageMessage({ chips: ['fever'], text: '' })).not.toMatch(/Discomfort/)
    expect(composeTriageMessage({ chips: ['fever'], text: '', level: null })).not.toMatch(/Discomfort/)
    expect(composeTriageMessage({ chips: ['fever'], text: '', level: 7 })).toContain('Discomfort level: 7/10 (moderate)')
  })

  it('offers examples in the chosen language and falls back to English', () => {
    expect(exampleFor('hi', 0)).toMatch(/[ऀ-ॿ]/)
    expect(exampleFor('te', 1)).toMatch(/[ఀ-౿]/)
    expect(exampleFor('ta', 2)).toMatch(/[஀-௿]/)
    expect(exampleFor('fr', 0)).toBe(exampleFor('en', 0))
    expect(exampleFor('en', 4)).toBe(exampleFor('en', 0)) // wraps around
    expect(exampleFor(undefined, -1)).toBe(exampleFor('en', 3))
  })

  it('shows four chips first and keeps the rest under More', () => {
    expect(SYMPTOM_CHIPS.filter((c) => c.primary).map((c) => c.id)).toEqual(['fever', 'cough', 'rash', 'stomach'])
    expect(SYMPTOM_CHIPS.length).toBeGreaterThan(4)
  })

  it('labels the discomfort slider and never offers a chest-pain chip', () => {
    expect([1, 3, 4, 7, 8, 10].map(discomfortLabel)).toEqual(['Mild', 'Mild', 'Moderate', 'Moderate', 'Urgent', 'Urgent'])
    expect(SYMPTOM_CHIPS.some((c) => /chest/i.test(c.label + c.phrase))).toBe(false)
  })
})

describe('calendar file (.ics)', () => {
  it('formats UTC timestamps', () => {
    expect(icsDate(new Date('2026-11-21T04:30:00Z'))).toBe('20261121T043000Z')
  })

  it('escapes the characters the format reserves', () => {
    expect(escapeIcsText('a, b; c\\d\nline')).toBe('a\\, b\\; c\\\\d\\nline')
  })

  it('folds long lines at 75 octets without breaking multi-byte characters', () => {
    const long = 'SUMMARY:' + 'నమస్కారం'.repeat(12)
    const folded = foldLine(long)
    const physical = folded.split('\r\n')
    expect(physical.length).toBeGreaterThan(1)
    expect(physical.every((l, i) => new TextEncoder().encode(i === 0 ? l : l).length <= 75)).toBe(true)
    expect(folded.replace(/\r\n /g, '')).toBe(long) // unfolding restores it exactly
  })

  it('builds a valid VEVENT with CRLF line endings and an alarm', () => {
    const ics = buildIcs({ uid: 'AP-1@x', start: new Date('2026-11-21T04:30:00Z'), end: new Date('2026-11-21T04:50:00Z'), summary: 'Visit, today', location: 'Guntur', stamp: new Date('2026-11-20T00:00:00Z') })
    expect(ics.startsWith('BEGIN:VCALENDAR\r\n')).toBe(true)
    expect(ics.endsWith('END:VCALENDAR\r\n')).toBe(true)
    expect(ics).toContain('DTSTART:20261121T043000Z\r\n')
    expect(ics).toContain('DTEND:20261121T045000Z\r\n')
    expect(ics).toContain('SUMMARY:Visit\\, today\r\n')
    expect(ics).toContain('TRIGGER:-PT60M\r\n')
    expect(ics.split('\r\n').every((l) => !l.includes('\n'))).toBe(true)
  })

  it('creates the entry for an appointment (video visits get an online location)', () => {
    const a = {
      ref: 'AP-CQDZM', starts_at: '2026-11-21T04:30:00Z', ends_at: '2026-11-21T04:50:00Z', patient_name: 'Ravi Kumar', reason: 'skin rash', mode: 'teleconsultation',
      provider: { name: 'Demo Skin & Care Clinic', doctor_name: 'Dr. M. Khan (demo)', address: null, city: 'Guntur' },
    } as unknown as Appointment
    const ics = appointmentToIcs(a)
    expect(ics).toContain('UID:AP-CQDZM@swasthya-saathi')
    expect(ics).toContain('SUMMARY:Doctor visit: Dr. M. Khan (demo)')
    expect(ics).toContain('LOCATION:Video visit (online)')
    expect(appointmentToIcs({ ...a, mode: 'in_person' } as Appointment)).toContain('LOCATION:Guntur')
  })
})

describe('slot grouping', () => {
  it('assigns periods at the 12:00 and 17:00 boundaries', () => {
    expect(['09:00', '11:40', '12:00', '16:40', '17:00', '19:20'].map(periodOf)).toEqual(['morning', 'morning', 'afternoon', 'afternoon', 'evening', 'evening'])
  })

  it('groups times, keeps order and drops empty groups', () => {
    const g = groupSlotsByPeriod(['10:00', '10:20', '17:00', '17:20'])
    expect(g.map((x) => x.label)).toEqual(['Morning', 'Evening'])
    expect(g[0]?.times).toEqual(['10:00', '10:20'])
    expect(groupSlotsByPeriod([])).toEqual([])
  })

  it('builds the date strip: Today / Tomorrow / weekday, with counts, only days that have slots', () => {
    const now = new Date('2026-11-20T06:00:00Z') // 11:30 IST on Fri 20 Nov
    const days = dayOptions({ '2026-11-22': ['10:00'], '2026-11-20': ['16:00', '16:20'], '2026-11-21': [], '2026-11-23': ['09:00', '09:20', '09:40'], '2026-11-24': ['10:00'] }, now)
    expect(days.map((d) => d.label)).toEqual(['Today', 'Sun', 'Mon', 'Tue'])
    expect(days.map((d) => d.dayNumber)).toEqual(['20', '22', '23', '24'])
    expect(days.map((d) => d.count)).toEqual([2, 1, 3, 1])
    expect(dayOptions({ '2026-11-21': ['10:00'] }, now)[0]?.label).toBe('Tomorrow')
  })

  it('uses the IST date for "today" (late evening UTC is already tomorrow in India)', () => {
    const now = new Date('2026-11-20T20:00:00Z') // 01:30 IST on 21 Nov
    expect(dayOptions({ '2026-11-21': ['10:00'] }, now)[0]?.label).toBe('Today')
  })

  it('formats the slot exactly as the API expects it', () => {
    expect(slotParam('2026-11-21', '10:20')).toBe('2026-11-21 10:20')
  })
})

describe('doctor avatars', () => {
  it('is deterministic per seed and different across seeds', () => {
    const a1 = avatarDataUri('HC-GNT-02')
    expect(avatarDataUri('HC-GNT-02')).toBe(a1)
    expect(avatarDataUri('hc-gnt-02 ')).toBe(a1) // seed is normalised
    expect(avatarDataUri('HC-HYD-01')).not.toBe(a1)
    expect(a1.startsWith('data:image/svg+xml')).toBe(true)
  })

  it('makes initials from names in any script, skipping titles and brackets', () => {
    expect(initials('Dr. M. Khan (demo)')).toBe('MK')
    expect(initials('Ravi Kumar')).toBe('RK')
    expect(initials('Guest')).toBe('G')
    expect(initials('లక్ష్మి దేవి')).toBe('లద')
    expect(initials('')).toBe('?')
    expect(initials(null)).toBe('?')
    expect(initials('Dr')).toBe('D')
  })
})

describe('rating display rule', () => {
  it('shows nothing until there is at least one real rating', () => {
    expect(ratingLabel({})).toBeNull()
    expect(ratingLabel({ rating_avg: null, rating_count: 0 })).toBeNull()
    expect(ratingLabel({ rating_avg: 4.9, rating_count: 0 })).toBeNull() // an average without ratings is not real
    expect(ratingLabel({ rating_avg: 4.9 })).toBeNull()
    expect(ratingLabel({ rating_avg: null, rating_count: 3 })).toBeNull()
    expect(ratingLabel({ rating_avg: 7, rating_count: 3 })).toBeNull()
  })

  it('shows score and review count when real', () => {
    expect(ratingLabel({ rating_avg: 4.85, rating_count: 24 })).toBe('4.9 (24 reviews)')
    expect(ratingLabel({ rating_avg: 5, rating_count: 1 })).toBe('5.0 (1 review)')
  })
})

describe('booking form rules', () => {
  const ok: BookingForm = { providerCode: 'HC-GNT-01', slot: { date: '2026-11-21', time: '10:20' }, mode: 'in_person', name: 'Ravi Kumar', mobile: '+91 98765 43210', reason: 'fever and cold' }

  it('normalises Indian mobile numbers', () => {
    expect(normalizeMobile('98765 43210')).toBe('9876543210')
    expect(normalizeMobile('+91-98765-43210')).toBe('9876543210')
    expect(normalizeMobile('919876543210')).toBe('9876543210')
    expect(normalizeMobile('5876543210')).toBeNull()
    expect(normalizeMobile('98765')).toBeNull()
    expect(normalizeMobile('')).toBeNull()
  })

  it('accepts a complete form and builds the exact API payload', () => {
    expect(validateBooking(ok)).toEqual({})
    expect(bookingPayload(ok, 'te')).toEqual({
      provider_code: 'HC-GNT-01', slot_start: '2026-11-21 10:20', patient_name: 'Ravi Kumar', patient_mobile: '9876543210', reason: 'fever and cold', mode: 'in_person', language: 'te',
    })
    expect('language' in bookingPayload(ok)).toBe(false)
  })

  it('reports every problem at once', () => {
    const e = validateBooking({ ...ok, slot: null, name: ' ', mobile: '123', reason: 'a' })
    expect(Object.keys(e).sort()).toEqual(['mobile', 'name', 'reason', 'slot'])
    expect(validateBooking({ ...ok, reason: 'x'.repeat(301) }).reason).toMatch(/300/)
  })

  it('refuses to build a payload from an invalid form', () => {
    expect(() => bookingPayload({ ...ok, slot: null })).toThrow()
    expect(() => bookingPayload({ ...ok, mobile: '1' })).toThrow()
  })

  it('maps server error codes to a message and an action', () => {
    expect(describeBookingError('slot_taken', '')).toMatchObject({ refreshSlots: true, field: 'slot' })
    expect(describeBookingError('slot_in_past', '').refreshSlots).toBe(true)
    expect(describeBookingError('invalid_mobile', '').field).toBe('mobile')
    expect(describeBookingError('no_teleconsultation', '').resetMode).toBe(true)
    expect(describeBookingError('too_many_appointments', '').message).toMatch(/Care Plan/)
    expect(describeBookingError('something_new', 'Server says hi').message).toBe('Server says hi')
    expect(describeBookingError('something_new', '').message).toMatch(/try again/i)
  })
})
