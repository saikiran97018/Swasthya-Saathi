import { describe, expect, it } from 'vitest'
import { bookingPayload, describeBookingError, validateBooking, type BookingForm } from './booking'

const now = new Date('2026-11-21T04:30:00Z') // 10:00 am IST

const base: BookingForm = { slot: { date: '2026-11-23', time: '10:20' }, mode: 'in_person', name: 'Ravi Kumar', mobile: '98765 43210', reason: 'fever and cold' }

describe('booking a partner clinic', () => {
  it('sends provider_code, the slot exactly as listed and the family member', () => {
    const body = bookingPayload({ ...base, providerCode: 'HC-1', familyMemberId: 'fam-1' }, 'te')
    expect(body).toEqual({ provider_code: 'HC-1', slot_start: '2026-11-23 10:20', patient_name: 'Ravi Kumar', patient_mobile: '9876543210', reason: 'fever and cold', mode: 'in_person', language: 'te', family_member_id: 'fam-1' })
    expect('place_id' in body).toBe(false)
  })

  it('leaves family_member_id out when booking for yourself', () => {
    expect('family_member_id' in bookingPayload({ ...base, providerCode: 'HC-1', familyMemberId: null })).toBe(false)
  })
})

describe('planning a visit at a map place', () => {
  it('sends place_id instead of provider_code, always in person', () => {
    const body = bookingPayload({ ...base, placeId: 'osm:node/123', mode: 'teleconsultation' })
    expect(body.place_id).toBe('osm:node/123')
    expect('provider_code' in body).toBe(false)
    expect(body.mode).toBe('in_person')
  })

  it('refuses to send both or neither', () => {
    expect(() => bookingPayload({ ...base, placeId: 'osm:node/1', providerCode: 'HC-1' })).toThrow()
    expect(() => bookingPayload({ ...base })).toThrow()
  })

  it('needs at least 2 hours of notice and at most 60 days', () => {
    const plan = { ...base, placeId: 'osm:node/1' }
    expect(validateBooking({ ...plan, slot: { date: '2026-11-21', time: '11:00' } }, now).slot).toMatch(/2 hours/)
    expect(validateBooking({ ...plan, slot: { date: '2026-11-21', time: '12:30' } }, now).slot).toBeUndefined()
    expect(validateBooking({ ...plan, slot: { date: '2027-03-01', time: '12:30' } }, now).slot).toMatch(/60 days/)
    // partner slots are chosen from the server's own list, so no client-side lead-time rule applies
    expect(validateBooking({ ...base, providerCode: 'HC-1', slot: { date: '2026-11-21', time: '10:20' } }, now).slot).toBeUndefined()
  })
})

describe('errors', () => {
  it('explains the new codes', () => {
    expect(describeBookingError('place_not_found', '').message).toMatch(/could not be found/)
    expect(describeBookingError('validation_error', '').message).toMatch(/not accepted/)
    expect(describeBookingError('slot_taken', '').refreshSlots).toBe(true)
  })
})
