import type { EmergencyContact, SosInfo, SosNumber } from '@/api/types'

/**
 * Pure helpers for the SOS screen: links the person taps (tel:, sms:, a maps link), the offline fallback numbers
 * and a tiny localStorage cache. Nothing here dials, sends or shares by itself.
 */

export const MAX_EMERGENCY_CONTACTS = 5

/** National numbers bundled with the app, so the SOS screen is useful even with no network and before the first load. */
export const FALLBACK_NUMBERS: SosNumber[] = [
  { code: '112', label: 'National emergency number', description: 'Police, fire and medical help from any phone in India.', kind: 'emergency' },
  { code: '108', label: 'Ambulance', description: 'Free emergency ambulance in most states.', kind: 'ambulance' },
  { code: '100', label: 'Police', description: 'Police control room.', kind: 'other' },
  { code: '101', label: 'Fire', description: 'Fire brigade.', kind: 'other' },
  { code: '181', label: 'Women helpline', description: 'Help for women in distress, any time.', kind: 'women' },
  { code: '1098', label: 'Childline', description: 'Help for a child in need of care or protection.', kind: 'child' },
  { code: '14416', label: 'Tele-MANAS', description: 'Free mental health counselling over the phone, in many languages.', kind: 'mental_health' },
]

export const FALLBACK_DISCLAIMER =
  'This page does not call or notify anyone by itself. If you or someone near you is in danger, call 112 now.'

/** What the screen shows when the server has never answered. */
export const FALLBACK_SOS: SosInfo = { numbers: FALLBACK_NUMBERS, nearby: [], first_aid: [], disclaimer: FALLBACK_DISCLAIMER }

/** Keep digits and a leading "+" only: what a tel: or sms: link needs. */
export function dialable(phone: string): string {
  const trimmed = phone.trim()
  const digits = trimmed.replace(/\D/g, '')
  return trimmed.startsWith('+') ? `+${digits}` : digits
}

export const telLink = (phone: string): string => `tel:${dialable(phone)}`

/** A 10-digit Indian mobile, or any number written with a country code, after removing spaces and dashes. */
export function isValidContactPhone(raw: string): boolean {
  const d = dialable(raw)
  const digits = d.replace(/\D/g, '')
  if (d.startsWith('+')) return digits.length >= 8 && digits.length <= 15
  return /^[6-9]\d{9}$/.test(digits) || /^91[6-9]\d{9}$/.test(digits)
}

export function isValidCoords(lat: number, lon: number): boolean {
  return Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180
}

/** `https://maps.google.com/?q=<lat>,<lon>`; 6 decimals is about 10 cm, plenty and short enough for an SMS. */
export function mapsLink(lat: number, lon: number): string {
  if (!isValidCoords(lat, lon)) throw new RangeError('Invalid coordinates')
  const f = (n: number) => String(Number(n.toFixed(6)))
  return `https://maps.google.com/?q=${f(lat)},${f(lon)}`
}

export const sosMessage = (link: string): string => `I need help. My location: ${link}`

/** `sms:<number>?body=<encoded text>`: opens the messaging app with the text ready; the person still taps Send. */
export function smsLink(phone: string, body: string): string {
  return `sms:${dialable(phone)}?body=${encodeURIComponent(body)}`
}

export type GeoFailure = 'unsupported' | 'denied' | 'unavailable' | 'timeout' | 'insecure'

export function geoErrorMessage(kind: GeoFailure): string {
  switch (kind) {
    case 'unsupported':
      return 'This browser cannot find your location. Call 112 and tell them where you are.'
    case 'insecure':
      return 'Location only works on a secure (https) page. Call 112 and tell them where you are.'
    case 'denied':
      return 'Location permission was turned off. You can allow it in your browser settings, or tell the person who answers where you are.'
    case 'timeout':
      return 'Finding your location took too long. Try again, or tell the person who answers where you are.'
    default:
      return 'Your location is not available right now. Try again, or tell the person who answers where you are.'
  }
}

/** Map a GeolocationPositionError code (1 denied, 2 unavailable, 3 timeout) to our failure kind. */
export function geoFailureFromCode(code: number): GeoFailure {
  return code === 1 ? 'denied' : code === 3 ? 'timeout' : 'unavailable'
}

// ---------------------------------------------------------------- local storage (always in try/catch)

const CACHE_KEY = 'ss.sos.v1'
const CITY_KEY = 'ss.sos.city'

export interface SosCache {
  savedAt: string
  city: string
  data: SosInfo
}

function isSosInfo(x: unknown): x is SosInfo {
  if (!x || typeof x !== 'object') return false
  const d = x as Record<string, unknown>
  return Array.isArray(d.numbers) && Array.isArray(d.nearby) && Array.isArray(d.first_aid) && typeof d.disclaimer === 'string'
}

export function writeSosCache(data: SosInfo, city: string, now: Date = new Date(), storage?: Pick<Storage, 'setItem'>): void {
  try {
    const s = storage ?? localStorage
    const value: SosCache = { savedAt: now.toISOString(), city: city.trim(), data }
    s.setItem(CACHE_KEY, JSON.stringify(value))
  } catch {
    /* storage full or blocked: the live answer still works */
  }
}

export function readSosCache(storage?: Pick<Storage, 'getItem'>): SosCache | null {
  try {
    const s = storage ?? localStorage
    const raw = s.getItem(CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<SosCache>
    if (!parsed || typeof parsed.savedAt !== 'string' || !isSosInfo(parsed.data)) return null
    return { savedAt: parsed.savedAt, city: typeof parsed.city === 'string' ? parsed.city : '', data: parsed.data }
  } catch {
    return null
  }
}

export function readSavedCity(storage?: Pick<Storage, 'getItem'>): string {
  try {
    return ((storage ?? localStorage).getItem(CITY_KEY) ?? '').slice(0, 80)
  } catch {
    return ''
  }
}

export function saveCity(city: string, storage?: Pick<Storage, 'setItem' | 'removeItem'>): void {
  try {
    const s = storage ?? localStorage
    const v = city.trim().slice(0, 80)
    if (v) s.setItem(CITY_KEY, v)
    else s.removeItem(CITY_KEY)
  } catch {
    /* ignore */
  }
}

/**
 * What to render: the live answer if there is one, else the cached one (marked "offline copy"), else the bundled numbers.
 * The cache's "nearby" list is only used when it was fetched for the same city that is asked for now.
 */
export function pickSos(live: SosInfo | undefined, cache: SosCache | null, city: string): { info: SosInfo; source: 'live' | 'cache' | 'bundled' } {
  if (live) return { info: live, source: 'live' }
  if (cache) {
    const sameCity = cache.city.toLowerCase() === city.trim().toLowerCase()
    return { info: sameCity ? cache.data : { ...cache.data, nearby: [] }, source: 'cache' }
  }
  return { info: FALLBACK_SOS, source: 'bundled' }
}

/** Always include 112 and 108 first, even if a server answer or cache is missing them. */
export function withNationalNumbers(numbers: SosNumber[]): SosNumber[] {
  const have = new Set(numbers.map((n) => n.code))
  const missing = FALLBACK_NUMBERS.filter((n) => (n.code === '112' || n.code === '108') && !have.has(n.code))
  return [...missing, ...numbers]
}

// ---------------------------------------------------------------- finding the person's location (only ever on a tap)

export interface Position {
  lat: number
  lon: number
  /** metres, when the device says */
  accuracy: number | null
}

export class GeoError extends Error {
  kind: GeoFailure
  constructor(kind: GeoFailure) {
    super(geoErrorMessage(kind))
    this.name = 'GeoError'
    this.kind = kind
  }
}

/**
 * Ask the browser for the current position. This is what triggers the permission prompt, so call it only from a tap.
 * `geo` and `secure` are injectable for tests.
 */
export function locate(
  geo: Pick<Geolocation, 'getCurrentPosition'> | undefined = typeof navigator !== 'undefined' ? navigator.geolocation : undefined,
  secure: boolean = typeof window === 'undefined' ? true : window.isSecureContext,
): Promise<Position> {
  return new Promise((resolve, reject) => {
    if (!geo) return reject(new GeoError('unsupported'))
    if (!secure) return reject(new GeoError('insecure'))
    geo.getCurrentPosition(
      (p) => {
        const { latitude: lat, longitude: lon, accuracy } = p.coords
        if (!isValidCoords(lat, lon)) return reject(new GeoError('unavailable'))
        resolve({ lat, lon, accuracy: Number.isFinite(accuracy) ? accuracy : null })
      },
      (e) => reject(new GeoError(geoFailureFromCode(e.code))),
      { enableHighAccuracy: true, timeout: 15_000, maximumAge: 30_000 },
    )
  })
}

// ---------------------------------------------------------------- offline copy of the emergency contacts

const CONTACTS_KEY = 'ss.sos.contacts.v1'

export function writeContactsCache(contacts: EmergencyContact[], storage?: Pick<Storage, 'setItem'>): void {
  try {
    ;(storage ?? localStorage).setItem(CONTACTS_KEY, JSON.stringify(contacts))
  } catch {
    /* ignore */
  }
}

export function readContactsCache(storage?: Pick<Storage, 'getItem'>): EmergencyContact[] {
  try {
    const raw = (storage ?? localStorage).getItem(CONTACTS_KEY)
    const parsed: unknown = raw ? JSON.parse(raw) : []
    if (!Array.isArray(parsed)) return []
    return parsed.filter((c): c is EmergencyContact => !!c && typeof c.id === 'string' && typeof c.name === 'string' && typeof c.phone === 'string')
  } catch {
    return []
  }
}
