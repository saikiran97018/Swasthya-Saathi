import { describe, expect, it } from 'vitest'
import type { SosInfo } from '@/api/types'
import { FALLBACK_NUMBERS, FALLBACK_SOS, dialable, locate, readContactsCache, writeContactsCache, geoFailureFromCode, isValidContactPhone, mapsLink, pickSos, readSavedCity, readSosCache, saveCity, smsLink, sosMessage, telLink, withNationalNumbers, writeSosCache } from './sos'

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial))
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
    data,
  }
}

const live: SosInfo = {
  numbers: [{ code: '112', label: 'National emergency', description: 'd', kind: 'emergency' }],
  nearby: [{ code: 'osm:node/1', name: 'Govt General Hospital', kind: 'hospital', city: 'Guntur', address: null, phone: null, teleconsultation: false, is_demo: false, source: 'openstreetmap' }],
  first_aid: [{ id: 'burn', title: 'Burns', steps: ['Cool the burn with running water'], call_if: 'The burn is large' }],
  disclaimer: 'x',
}

describe('links', () => {
  it('builds the maps link in the agreed format', () => {
    expect(mapsLink(16.3067, 80.4365)).toBe('https://maps.google.com/?q=16.3067,80.4365')
    expect(mapsLink(-33.8688, 151.2093)).toBe('https://maps.google.com/?q=-33.8688,151.2093')
  })

  it('trims very long coordinates to 6 decimals and rejects invalid ones', () => {
    expect(mapsLink(16.123456789, 80.987654321)).toBe('https://maps.google.com/?q=16.123457,80.987654')
    expect(() => mapsLink(91, 10)).toThrow()
    expect(() => mapsLink(10, Number.NaN)).toThrow()
  })

  it('cleans phone numbers for tel: and keeps a leading plus', () => {
    expect(dialable(' 98765 43210 ')).toBe('9876543210')
    expect(dialable('+91 98765-43210')).toBe('+919876543210')
    expect(telLink('1800 180 1104')).toBe('tel:18001801104')
  })

  it('encodes the sms body so the maps link survives', () => {
    const body = sosMessage(mapsLink(16.3, 80.4))
    expect(body).toBe('I need help. My location: https://maps.google.com/?q=16.3,80.4')
    const link = smsLink('+91 98765 43210', body)
    expect(link.startsWith('sms:+919876543210?body=')).toBe(true)
    expect(link).not.toContain(' ')
    expect(link).not.toContain('?q=')
    const encoded = link.split('?body=')[1] ?? ''
    expect(decodeURIComponent(encoded)).toBe(body)
  })
})

describe('contact phone validation', () => {
  it('accepts Indian mobiles and international numbers, rejects junk', () => {
    expect(isValidContactPhone('98765 43210')).toBe(true)
    expect(isValidContactPhone('+91 98765 43210')).toBe(true)
    expect(isValidContactPhone('919876543210')).toBe(true)
    expect(isValidContactPhone('+44 7911 123456')).toBe(true)
    expect(isValidContactPhone('12345')).toBe(false)
    expect(isValidContactPhone('5876543210')).toBe(false)
    expect(isValidContactPhone('')).toBe(false)
  })
})

describe('geolocation errors', () => {
  it('maps browser error codes', () => {
    expect(geoFailureFromCode(1)).toBe('denied')
    expect(geoFailureFromCode(2)).toBe('unavailable')
    expect(geoFailureFromCode(3)).toBe('timeout')
  })
})

describe('cache', () => {
  it('writes and reads back the last successful answer', () => {
    const s = memoryStorage()
    const when = new Date('2026-11-21T10:00:00Z')
    writeSosCache(live, '  Guntur ', when, s)
    const back = readSosCache(s)
    expect(back).not.toBeNull()
    expect(back?.city).toBe('Guntur')
    expect(back?.savedAt).toBe(when.toISOString())
    expect(back?.data).toEqual(live)
  })

  it('returns null for empty, corrupt or wrongly-shaped data', () => {
    expect(readSosCache(memoryStorage())).toBeNull()
    expect(readSosCache(memoryStorage({ 'ss.sos.v1': '{not json' }))).toBeNull()
    expect(readSosCache(memoryStorage({ 'ss.sos.v1': JSON.stringify({ savedAt: 'x', data: { numbers: 1 } }) }))).toBeNull()
  })

  it('never throws when storage is blocked', () => {
    const blocked = {
      getItem: () => {
        throw new Error('blocked')
      },
      setItem: () => {
        throw new Error('blocked')
      },
      removeItem: () => {
        throw new Error('blocked')
      },
    }
    expect(() => writeSosCache(live, '', new Date(), blocked)).not.toThrow()
    expect(readSosCache(blocked)).toBeNull()
    expect(readSavedCity(blocked)).toBe('')
    expect(() => saveCity('Guntur', blocked)).not.toThrow()
  })

  it('remembers the city and forgets it when cleared', () => {
    const s = memoryStorage()
    expect(readSavedCity(s)).toBe('')
    saveCity(' Guntur ', s)
    expect(readSavedCity(s)).toBe('Guntur')
    saveCity('   ', s)
    expect(readSavedCity(s)).toBe('')
  })
})

describe('pickSos', () => {
  it('prefers live data, then the cache, then the bundled numbers', () => {
    expect(pickSos(live, null, '').source).toBe('live')
    const cache = { savedAt: 'x', city: 'Guntur', data: live }
    const fromCache = pickSos(undefined, cache, 'guntur')
    expect(fromCache.source).toBe('cache')
    expect(fromCache.info.nearby).toHaveLength(1)
    const none = pickSos(undefined, null, '')
    expect(none.source).toBe('bundled')
    expect(none.info).toBe(FALLBACK_SOS)
  })

  it('drops cached nearby places that belong to another city', () => {
    const cache = { savedAt: 'x', city: 'Guntur', data: live }
    const other = pickSos(undefined, cache, 'Hyderabad')
    expect(other.info.nearby).toEqual([])
    expect(other.info.first_aid).toHaveLength(1)
  })
})

describe('national numbers', () => {
  it('bundle contains 112 and 108 first', () => {
    expect(FALLBACK_NUMBERS[0]?.code).toBe('112')
    expect(FALLBACK_NUMBERS[1]?.code).toBe('108')
  })

  it('adds 112 and 108 when an answer lacks them', () => {
    const merged = withNationalNumbers([{ code: '181', label: 'Women', description: '', kind: 'women' }])
    expect(merged.map((n) => n.code)).toEqual(['112', '108', '181'])
    expect(withNationalNumbers(FALLBACK_NUMBERS)).toHaveLength(FALLBACK_NUMBERS.length)
  })
})

describe('locate', () => {
  const ok = (lat: number, lon: number) => ({ getCurrentPosition: (s: PositionCallback) => s({ coords: { latitude: lat, longitude: lon, accuracy: 20 } } as GeolocationPosition) })
  const fail = (code: number) => ({ getCurrentPosition: (_s: PositionCallback, e?: PositionErrorCallback | null) => e?.({ code } as GeolocationPositionError) })

  it('resolves with the position', async () => {
    await expect(locate(ok(16.3, 80.4), true)).resolves.toEqual({ lat: 16.3, lon: 80.4, accuracy: 20 })
  })

  it('reports each failure kind without throwing strings', async () => {
    await expect(locate(undefined, true)).rejects.toMatchObject({ kind: 'unsupported' })
    await expect(locate(ok(1, 1), false)).rejects.toMatchObject({ kind: 'insecure' })
    await expect(locate(fail(1), true)).rejects.toMatchObject({ kind: 'denied' })
    await expect(locate(fail(3), true)).rejects.toMatchObject({ kind: 'timeout' })
    await expect(locate(ok(999, 1), true)).rejects.toMatchObject({ kind: 'unavailable' })
  })
})

describe('contacts cache', () => {
  it('round-trips and ignores junk', () => {
    const s = memoryStorage()
    const c = [{ id: '1', name: 'Amma', phone: '9876543210', relation: 'parent', created_at: 'x' }]
    writeContactsCache(c, s)
    expect(readContactsCache(s)).toEqual(c)
    expect(readContactsCache(memoryStorage({ 'ss.sos.contacts.v1': '{"a":1}' }))).toEqual([])
    expect(readContactsCache(memoryStorage({ 'ss.sos.contacts.v1': '[1,{"id":"1"}]' }))).toEqual([])
  })
})
