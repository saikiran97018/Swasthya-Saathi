import type { CreateAppointmentBody } from '@/api/types'
import { validatePlannedSlot } from './places'
import { slotParam } from './slots'

/** 10-digit Indian mobile starting with 6-9. Accepts spaces, dashes and a +91 / 91 prefix; returns the 10 digits or null. */
export function normalizeMobile(raw: string): string | null {
  let digits = raw.replace(/\D/g, '')
  if (digits.length === 12 && digits.startsWith('91')) digits = digits.slice(2)
  return /^[6-9]\d{9}$/.test(digits) ? digits : null
}

export interface BookingForm {
  /** A partner clinic with online slots (booked). Set this OR placeId. */
  providerCode?: string
  /** A map place without online slots ("plan a visit", not confirmed by the clinic). */
  placeId?: string
  slot: { date: string; time: string } | null
  mode: 'in_person' | 'teleconsultation'
  name: string
  mobile: string
  reason: string
  /** A saved family member the visit is for; leave out when booking for yourself. */
  familyMemberId?: string | null
}

export type BookingField = 'slot' | 'name' | 'mobile' | 'reason'

/** Client-side checks that mirror the server rules, so the person sees what to fix before anything is sent. */
export function validateBooking(f: BookingForm, now: Date = new Date()): Partial<Record<BookingField, string>> {
  const errors: Partial<Record<BookingField, string>> = {}
  if (!f.slot) errors.slot = 'Choose a date and a time.'
  else if (f.placeId) {
    const planned = validatePlannedSlot(f.slot.date, f.slot.time, now)
    if (planned) errors.slot = planned
  }
  const name = f.name.trim()
  if (name.length < 2) errors.name = 'Enter the patient\'s full name.'
  else if (name.length > 80) errors.name = 'The name is too long (80 letters at most).'
  if (!normalizeMobile(f.mobile)) errors.mobile = 'Enter a 10-digit mobile number starting with 6, 7, 8 or 9.'
  const reason = f.reason.trim()
  if (reason.length < 3) errors.reason = 'Tell us briefly why you want to see the doctor.'
  else if (reason.length > 300) errors.reason = 'Please keep the reason under 300 characters.'
  return errors
}

export function bookingPayload(f: BookingForm, language?: string): CreateAppointmentBody {
  if (!f.slot) throw new Error('No slot selected')
  const mobile = normalizeMobile(f.mobile)
  if (!mobile) throw new Error('Invalid mobile number')
  if (!!f.providerCode === !!f.placeId) throw new Error('Send exactly one of provider_code or place_id')
  return {
    ...(f.placeId ? { place_id: f.placeId } : { provider_code: f.providerCode }),
    slot_start: slotParam(f.slot.date, f.slot.time),
    patient_name: f.name.trim(),
    patient_mobile: mobile,
    reason: f.reason.trim(),
    mode: f.placeId ? 'in_person' : f.mode,
    ...(language ? { language } : {}),
    ...(f.familyMemberId ? { family_member_id: f.familyMemberId } : {}),
  }
}

export interface BookingErrorEffect {
  message: string
  /** Re-fetch the free slots and clear the chosen one (it is no longer valid). */
  refreshSlots?: boolean
  /** Show the message next to this field. */
  field?: BookingField
  /** Switch back to an in-person visit. */
  resetMode?: boolean
}

/** What to do and say for each error code the booking endpoint can return. */
export function describeBookingError(code: string, fallback: string): BookingErrorEffect {
  switch (code) {
    case 'slot_taken':
      return { message: 'That time was just taken by someone else. Please pick another time.', refreshSlots: true, field: 'slot' }
    case 'slot_in_past':
      return { message: 'That time has already passed or is too close. Please pick a later time.', refreshSlots: true, field: 'slot' }
    case 'slot_too_far':
      return { message: 'That date is too far ahead to book. Please pick an earlier date.', refreshSlots: true, field: 'slot' }
    case 'invalid_slot':
      return { message: 'That time is not available any more. Please pick one from the list.', refreshSlots: true, field: 'slot' }
    case 'invalid_mobile':
      return { message: 'Enter a 10-digit mobile number starting with 6, 7, 8 or 9.', field: 'mobile' }
    case 'too_many_appointments':
      return { message: 'You already have the maximum number of upcoming appointments. Cancel one in Care Plan before booking another.' }
    case 'user_conflict':
      return { message: 'You already have an appointment at that time. Choose a different time.', field: 'slot' }
    case 'no_teleconsultation':
      return { message: 'This provider does not offer video visits. Please choose an in-person visit.', resetMode: true }
    case 'place_not_found':
      return { message: 'This place could not be found any more. Please go back and choose another.' }
    case 'validation_error':
      return { message: 'Some details were not accepted. Please check the date, time and your details, then try again.' }
    case 'provider_not_found':
      return { message: 'This provider is no longer listed. Please go back and choose another.' }
    default:
      return { message: fallback || 'We could not book the appointment. Please try again.' }
  }
}
