import type { Place, PlaceKind, PlaceQuery } from '@/api/types'
import { dialable } from './sos'
import { istDateKey } from './time'

/** Plain-language labels for what a place is. */
export const PLACE_KIND_LABEL: Record<PlaceKind, string> = { hospital: 'Hospital', clinic: 'Clinic', doctor: 'Doctor', phc: 'Health centre', other: 'Care place' }

export const placeKindLabel = (k: string): string => PLACE_KIND_LABEL[k as PlaceKind] ?? 'Care place'

/** Google Maps directions to a point. Opens the maps app on a phone; nothing is sent from here. */
export function directionsLink(lat: number, lon: number): string {
  return `https://www.google.com/maps/dir/?api=1&destination=${Number(lat.toFixed(6))},${Number(lon.toFixed(6))}`
}

/** "850 m away", "3.2 km away", "12 km away"; null when the server did not give a distance. */
export function distanceLabel(km: number | null | undefined): string | null {
  if (km === null || km === undefined || !Number.isFinite(km) || km < 0) return null
  if (km < 1) return `${Math.max(50, Math.round((km * 1000) / 50) * 50)} m away`
  return `${km < 10 ? km.toFixed(1) : Math.round(km)} km away`
}

/** A website is only shown as a link when it is plain http(s) (map data is user-edited, so never trust other schemes). */
export function safeWebsite(url: string | null | undefined): string | null {
  if (!url) return null
  const u = url.trim()
  const withScheme = /^[a-z][a-z0-9+.-]*:/i.test(u) ? u : `https://${u}`
  try {
    const parsed = new URL(withScheme)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.toString() : null
  } catch {
    return null
  }
}

export function websiteHost(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, '')
  } catch {
    return url
  }
}

/** Two modes of booking: partner clinics with online slots are booked; everything else is a planned visit. */
export type VisitMode = 'book' | 'plan'

export const visitModeFor = (p: Pick<Place, 'source' | 'has_slots' | 'provider_code'>): VisitMode => (p.source === 'partner' && p.has_slots && !!p.provider_code ? 'book' : 'plan')

/** The text that goes under a place name: address and city, without printing the city twice. */
export function placeAddress(p: Pick<Place, 'address' | 'city'>): string {
  const parts: string[] = []
  for (const x of [p.address, p.city]) if (x && !parts.some((y) => y.toLowerCase().includes(x.toLowerCase()))) parts.push(x)
  return parts.join(', ')
}

export interface PlaceFilters {
  city: string
  coords: { lat: number; lon: number } | null
  kind: '' | 'hospital' | 'clinic' | 'doctor'
  q: string
  specialty?: string
}

/** The search to run, or null when there is nothing to search around yet. Coordinates win over a typed city. */
export function placeQueryFrom(f: PlaceFilters): PlaceQuery | null {
  const city = f.city.trim()
  const q = f.q.trim()
  const base: PlaceQuery = { ...(f.kind && { kind: f.kind }), ...(q && { q }), ...(f.specialty && { specialty: f.specialty }) }
  if (f.coords) return { ...base, lat: Number(f.coords.lat.toFixed(5)), lon: Number(f.coords.lon.toFixed(5)) }
  if (city) return { ...base, city }
  return null
}

const CITY_KEY = 'ss.care.city'

export function readCareCity(storage?: Pick<Storage, 'getItem'>): string {
  try {
    return ((storage ?? localStorage).getItem(CITY_KEY) ?? '').slice(0, 80)
  } catch {
    return ''
  }
}

export function saveCareCity(city: string, storage?: Pick<Storage, 'setItem' | 'removeItem'>): void {
  try {
    const s = storage ?? localStorage
    const v = city.trim().slice(0, 80)
    if (v) s.setItem(CITY_KEY, v)
    else s.removeItem(CITY_KEY)
  } catch {
    /* ignore */
  }
}

// ---------------------------------------------------------------- planning a visit (no online slots)

export const PLAN_MIN_LEAD_HOURS = 2
export const PLAN_MAX_DAYS = 60

/** "2026-11-23" + "10:30" in IST as an instant, or null if either part is malformed. IST has no daylight saving, so +05:30 is always right. */
export function istInstant(date: string, time: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !/^\d{2}:\d{2}$/.test(time)) return null
  const d = new Date(`${date}T${time}:00+05:30`)
  return Number.isNaN(d.getTime()) ? null : d
}

/** The first and last calendar dates (IST, YYYY-MM-DD) a visit can be planned for. */
export function planDateBounds(now: Date = new Date()): { min: string; max: string } {
  return { min: istDateKey(new Date(now.getTime() + PLAN_MIN_LEAD_HOURS * 3_600_000)), max: istDateKey(new Date(now.getTime() + PLAN_MAX_DAYS * 86_400_000)) }
}

/** An error message, or null when the date and time are fine: at least 2 hours from now and within 60 days. */
export function validatePlannedSlot(date: string, time: string, now: Date = new Date()): string | null {
  if (!date) return 'Choose a date.'
  if (!time) return 'Choose a time.'
  const at = istInstant(date, time)
  if (!at) return 'Enter the date and time again.'
  if (at.getTime() < now.getTime() + PLAN_MIN_LEAD_HOURS * 3_600_000) return `Choose a time at least ${PLAN_MIN_LEAD_HOURS} hours from now (India time).`
  if (at.getTime() > now.getTime() + PLAN_MAX_DAYS * 86_400_000) return `Choose a date within the next ${PLAN_MAX_DAYS} days.`
  return null
}

/** `tel:` link for a phone number from the map data (which can hold several numbers or free text), or null if there is no usable number. */
export function telLinkFor(phone: string | null | undefined): string | null {
  if (!phone) return null
  const first = phone.split(/[;,/]/)[0] ?? ''
  const d = dialable(first)
  return d.replace(/\D/g, '').length >= 5 ? `tel:${d}` : null
}
