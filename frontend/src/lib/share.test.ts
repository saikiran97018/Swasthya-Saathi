import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Appointment } from '@/api/types'
import { appointmentShareText, shareAppointment, whatsappLink } from './share'

const appt = {
  ref: 'AP-7K3QX', starts_at: '2026-11-23T05:00:00Z', mode: 'in_person', patient_name: 'Ravi Kumar', patient_mobile: '98XXXXXX10', clinic_confirmed: true,
  provider: { name: 'Dr Rao Clinic', address: 'Brodipet', city: 'Guntur', phone: '08632111111' },
} as unknown as Appointment

afterEach(() => vi.unstubAllGlobals())

describe('appointmentShareText', () => {
  it('says who, when, where, the clinic phone and the reference', () => {
    const t = appointmentShareText(appt)
    expect(t).toContain('Doctor visit for Ravi Kumar')
    expect(t).toMatch(/When: .*10:30 am IST/i) // 05:00 UTC is 10:30 in India
    expect(t).toContain('Where: Dr Rao Clinic, Brodipet, Guntur')
    expect(t).toContain('Clinic phone: 08632111111')
    expect(t).toContain('Reference: AP-7K3QX')
  })
  it('never includes the patient mobile number', () => {
    expect(appointmentShareText(appt)).not.toMatch(/98XXXXXX10|9876/)
  })
  it('asks to confirm a planned visit and skips a missing phone', () => {
    const t = appointmentShareText({ ...appt, clinic_confirmed: false, provider: { ...appt.provider, phone: null } } as unknown as Appointment)
    expect(t).toContain('Not yet confirmed by the clinic')
    expect(t).not.toContain('Clinic phone')
  })
  it('describes a video visit without an address', () => {
    expect(appointmentShareText({ ...appt, mode: 'teleconsultation' } as unknown as Appointment)).toContain('Video visit')
  })
})

describe('sharing', () => {
  it('builds a WhatsApp link with the text encoded', () => {
    expect(whatsappLink('a b\nc')).toBe('https://wa.me/?text=a%20b%0Ac')
  })
  it('uses the phone share sheet when there is one', async () => {
    const share = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { share })
    expect(await shareAppointment(appt)).toBe('shared')
    expect(share.mock.calls[0]?.[0]?.text).toContain('AP-7K3QX')
  })
  it('does nothing more when the person closes the share sheet', async () => {
    vi.stubGlobal('navigator', { share: vi.fn().mockRejectedValue(new DOMException('x', 'AbortError')) })
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    expect(await shareAppointment(appt)).toBe('cancelled')
    expect(open).not.toHaveBeenCalled()
  })
  it('falls back to WhatsApp when sharing is not available', async () => {
    vi.stubGlobal('navigator', {})
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    expect(await shareAppointment(appt)).toBe('whatsapp')
    expect(open.mock.calls[0]?.[0]).toMatch(/^https:\/\/wa\.me\/\?text=/)
  })
})
