import { describe, expect, it } from 'vitest'
import { fmtVaccineDate, statusLabel } from './vaccines'
import { notificationPrefill } from './notifications'

describe('vaccine labels', () => {
  it('writes a date-only value without shifting the day', () => {
    expect(fmtVaccineDate('2026-02-21')).toBe('21 Feb 2026')
    expect(fmtVaccineDate('2026-01-01')).toBe('1 Jan 2026')
    expect(fmtVaccineDate('nonsense')).toBe('nonsense')
  })
  it('says what each status means in plain words', () => {
    expect(statusLabel({ status: 'given' })).toBe('Done')
    expect(statusLabel({ status: 'overdue' })).toBe('Overdue')
    expect(statusLabel({ status: 'due' })).toBe('Due now')
    expect(statusLabel({ status: 'upcoming' })).toBe('Coming up')
  })
})

describe('opening the new notifications', () => {
  it('puts a draft in the composer, never sends it', () => {
    expect(notificationPrefill({ kind: 'symptom_checkin', appointment_ref: null })).toBe('Update on how I am feeling: ')
    expect(notificationPrefill({ kind: 'vaccine', appointment_ref: null })).toMatch(/vaccines that are due/)
    expect(notificationPrefill({ kind: 'medicine', appointment_ref: null })).toBeNull()
  })
})
