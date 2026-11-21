import { describe, expect, it } from 'vitest'
import { directionsLink, distanceLabel, istInstant, placeAddress, placeQueryFrom, planDateBounds, readCareCity, safeWebsite, saveCareCity, telLinkFor, validatePlannedSlot, visitModeFor } from './places'

const now = new Date('2026-11-21T04:30:00Z') // 10:00 am IST on Sat 21 Nov 2026

describe('links and labels', () => {
  it('builds the directions link', () => {
    expect(directionsLink(16.3067, 80.4365)).toBe('https://www.google.com/maps/dir/?api=1&destination=16.3067,80.4365')
  })

  it('labels distance, or nothing when unknown', () => {
    expect(distanceLabel(0.42)).toBe('400 m away')
    expect(distanceLabel(3.24)).toBe('3.2 km away')
    expect(distanceLabel(12.6)).toBe('13 km away')
    expect(distanceLabel(null)).toBeNull()
    expect(distanceLabel(-1)).toBeNull()
  })

  it('only links http(s) websites', () => {
    expect(safeWebsite('https://clinic.example/about')).toBe('https://clinic.example/about')
    expect(safeWebsite('clinic.example')).toBe('https://clinic.example/')
    expect(safeWebsite('javascript:alert(1)')).toBeNull()
    expect(safeWebsite('')).toBeNull()
    expect(safeWebsite(null)).toBeNull()
  })

  it('does not print the city twice', () => {
    expect(placeAddress({ address: 'Brodipet, Guntur', city: 'Guntur' })).toBe('Brodipet, Guntur')
    expect(placeAddress({ address: '12 Main Road', city: 'Guntur' })).toBe('12 Main Road, Guntur')
    expect(placeAddress({ address: null, city: null })).toBe('')
  })
})

describe('visit mode', () => {
  it('books only partner places with slots, otherwise plans', () => {
    expect(visitModeFor({ source: 'partner', has_slots: true, provider_code: 'P1' })).toBe('book')
    expect(visitModeFor({ source: 'partner', has_slots: false, provider_code: 'P1' })).toBe('plan')
    expect(visitModeFor({ source: 'openstreetmap', has_slots: false, provider_code: null })).toBe('plan')
    expect(visitModeFor({ source: 'openstreetmap', has_slots: true, provider_code: null })).toBe('plan')
  })
})

describe('search query', () => {
  it('needs a city or coordinates', () => {
    expect(placeQueryFrom({ city: '  ', coords: null, kind: '', q: '' })).toBeNull()
    expect(placeQueryFrom({ city: ' Guntur ', coords: null, kind: 'clinic', q: ' skin ' })).toEqual({ city: 'Guntur', kind: 'clinic', q: 'skin' })
  })

  it('prefers coordinates over a typed city', () => {
    expect(placeQueryFrom({ city: 'Guntur', coords: { lat: 16.306712345, lon: 80.4365 }, kind: '', q: '' })).toEqual({ lat: 16.30671, lon: 80.4365 })
  })
})

describe('city storage', () => {
  it('remembers and clears, and survives blocked storage', () => {
    const m = new Map<string, string>()
    const s = { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k) }
    saveCareCity(' Guntur ', s)
    expect(readCareCity(s)).toBe('Guntur')
    saveCareCity('', s)
    expect(readCareCity(s)).toBe('')
    const boom = () => {
      throw new Error('blocked')
    }
    const blocked = { getItem: boom, setItem: boom, removeItem: boom }
    expect(readCareCity(blocked)).toBe('')
    expect(() => saveCareCity('a', blocked)).not.toThrow()
  })
})

describe('planned visit time', () => {
  it('parses IST date and time', () => {
    expect(istInstant('2026-11-21', '10:00')?.toISOString()).toBe('2026-11-21T04:30:00.000Z')
    expect(istInstant('21-11-2026', '10:00')).toBeNull()
    expect(istInstant('2026-11-21', '10am')).toBeNull()
  })

  it('needs at least 2 hours of notice (IST)', () => {
    expect(validatePlannedSlot('2026-11-21', '11:59', now)).toMatch(/at least 2 hours/)
    expect(validatePlannedSlot('2026-11-21', '12:00', now)).toBeNull()
    expect(validatePlannedSlot('2026-11-20', '12:00', now)).toMatch(/at least 2 hours/)
    expect(validatePlannedSlot('2026-11-22', '09:00', now)).toBeNull()
  })

  it('allows up to 60 days ahead', () => {
    expect(validatePlannedSlot('2027-01-20', '10:00', now)).toBeNull()
    expect(validatePlannedSlot('2027-01-21', '11:00', now)).toMatch(/within the next 60 days/)
  })

  it('asks for missing parts', () => {
    expect(validatePlannedSlot('', '10:00', now)).toBe('Choose a date.')
    expect(validatePlannedSlot('2026-11-22', '', now)).toBe('Choose a time.')
  })

  it('gives date bounds in IST', () => {
    expect(planDateBounds(now)).toEqual({ min: '2026-11-21', max: '2027-01-20' })
    // 22:00 IST: two hours later is already the next calendar day
    expect(planDateBounds(new Date('2026-11-21T16:30:00Z')).min).toBe('2026-11-22')
  })
})

describe('telLinkFor', () => {
  it('makes a tel link from the first number and ignores junk', () => {
    expect(telLinkFor('+91 863 222 1234')).toBe('tel:+918632221234')
    expect(telLinkFor('0863 2221234; 98765 43210')).toBe('tel:08632221234')
    expect(telLinkFor('ask at the desk')).toBeNull()
    expect(telLinkFor(null)).toBeNull()
  })
})
