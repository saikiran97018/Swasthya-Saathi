import type { Appointment } from '@/api/types'

/** Minimal RFC 5545 calendar file, so a visit can be added to any calendar app. */

const pad = (n: number) => String(n).padStart(2, '0')

/** UTC "20261121T043000Z". */
export function icsDate(d: Date): string {
  return `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}T${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}Z`
}

export function escapeIcsText(s: string): string {
  return s.replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n')
}

/** Lines longer than 75 octets must be folded (CRLF + one space), without splitting a multi-byte character. */
export function foldLine(line: string): string {
  const enc = new TextEncoder()
  if (enc.encode(line).length <= 75) return line
  const parts: string[] = []
  let cur = ''
  let bytes = 0
  let limit = 75
  for (const ch of line) {
    const b = enc.encode(ch).length
    if (bytes + b > limit) {
      parts.push(cur)
      cur = ''
      bytes = 0
      limit = 74 // continuation lines start with a space that counts too
    }
    cur += ch
    bytes += b
  }
  parts.push(cur)
  return parts.join('\r\n ')
}

export interface IcsEvent {
  uid: string
  start: Date
  end: Date
  summary: string
  description?: string
  location?: string
  /** Pop up a reminder this many minutes before (default 60). */
  alarmMinutes?: number
  stamp?: Date
}

export function buildIcs(e: IcsEvent): string {
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//Swasthya Saathi//Care Plan//EN',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    'BEGIN:VEVENT',
    `UID:${e.uid}`,
    `DTSTAMP:${icsDate(e.stamp ?? new Date())}`,
    `DTSTART:${icsDate(e.start)}`,
    `DTEND:${icsDate(e.end)}`,
    `SUMMARY:${escapeIcsText(e.summary)}`,
    ...(e.description ? [`DESCRIPTION:${escapeIcsText(e.description)}`] : []),
    ...(e.location ? [`LOCATION:${escapeIcsText(e.location)}`] : []),
    'BEGIN:VALARM',
    `TRIGGER:-PT${Math.max(1, Math.round(e.alarmMinutes ?? 60))}M`,
    'ACTION:DISPLAY',
    `DESCRIPTION:${escapeIcsText(e.summary)}`,
    'END:VALARM',
    'END:VEVENT',
    'END:VCALENDAR',
  ]
  return lines.map(foldLine).join('\r\n') + '\r\n'
}

/** The calendar entry for a booked appointment (times are real instants, so every calendar shows the right local time). */
export function appointmentToIcs(a: Appointment): string {
  const p = a.provider
  const who = p.doctor_name ?? p.name
  const video = a.mode === 'teleconsultation'
  return buildIcs({
    uid: `${a.ref}@swasthya-saathi`,
    start: new Date(a.starts_at),
    end: new Date(a.ends_at),
    summary: `Doctor visit: ${who}`,
    description: [`Reference: ${a.ref}`, `Patient: ${a.patient_name}`, `Reason: ${a.reason}`, `Clinic: ${p.name}`, 'The visit time is in Indian Standard Time (IST).'].join('\n'),
    location: video ? 'Video visit (online)' : [p.address, p.city].filter(Boolean).join(', ') || p.name,
  })
}

/** Download text as a file (browser only). */
export function downloadTextFile(filename: string, content: string, mime = 'text/calendar;charset=utf-8') {
  const url = URL.createObjectURL(new Blob([content], { type: mime }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
