import type { Appointment } from '@/api/types'

/**
 * Text to send a family member about a visit: who, where, when, the reference, and the phone number of the clinic.
 * The patient's own mobile number is never included.
 */
export function appointmentShareText(a: Appointment): string {
  const when = new Date(a.starts_at).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hour12: true })
  const p = a.provider
  const where = a.mode === 'teleconsultation' ? 'Video visit (the clinic will share the link)' : [p.name, p.address, p.city].filter((x, i, arr) => x && arr.indexOf(x) === i).join(', ')
  const lines = [
    `Doctor visit for ${a.patient_name}`,
    `When: ${when} IST`,
    `Where: ${where}`,
    p.phone ? `Clinic phone: ${p.phone}` : null,
    `Reference: ${a.ref}`,
    a.clinic_confirmed === false ? 'Not yet confirmed by the clinic: please phone them to confirm the time.' : null,
  ]
  return lines.filter(Boolean).join('\n')
}

export const whatsappLink = (text: string): string => `https://wa.me/?text=${encodeURIComponent(text)}`

/** Any text: the phone's share sheet, else WhatsApp in a new tab. */
export async function shareText(text: string, title: string): Promise<'shared' | 'whatsapp' | 'cancelled'> {
  if (typeof navigator !== 'undefined' && typeof navigator.share === 'function') {
    try {
      await navigator.share({ title, text })
      return 'shared'
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return 'cancelled'
    }
  }
  window.open(whatsappLink(text), '_blank', 'noopener,noreferrer')
  return 'whatsapp'
}

/** The phone's own share sheet when there is one (WhatsApp, SMS ...), otherwise WhatsApp in a new tab. */
export function shareAppointment(a: Appointment): Promise<'shared' | 'whatsapp' | 'cancelled'> {
  return shareText(appointmentShareText(a), 'Doctor visit')
}
