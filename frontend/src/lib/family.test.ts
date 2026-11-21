import { describe, expect, it } from 'vitest'
import type { FamilyMember } from '@/api/types'
import { EMPTY_FAMILY_FORM, ageFromBirthYear, bookingFieldsFor, familyCreateBody, familyPatchBody, forLabel, formFromMember, memberSubtitle, relationLabel, validateFamilyForm } from './family'

const now = new Date('2026-11-21T10:00:00Z')

const asha: FamilyMember = { id: 'f1', name: 'Asha Kumar', relation: 'child', birth_year: 2019, gender: 'female', mobile: '9876543210', language: 'te', created_at: '2026-01-01T00:00:00Z' }

describe('age', () => {
  it('is computed from the birth year', () => {
    expect(ageFromBirthYear(2019, now)).toBe(7)
    expect(ageFromBirthYear(2026, now)).toBe(0)
    expect(ageFromBirthYear(null, now)).toBeNull()
    expect(ageFromBirthYear(2030, now)).toBeNull()
    expect(ageFromBirthYear(1800, now)).toBeNull()
  })

  it('reads well in the list', () => {
    expect(memberSubtitle(asha, now)).toBe('Child · 7 years')
    expect(memberSubtitle({ relation: 'parent', birth_year: 1960 }, now)).toBe('Parent · 66 years')
    expect(memberSubtitle({ relation: 'child', birth_year: 2025 }, now)).toBe('Child · 1 year')
    expect(memberSubtitle({ relation: 'child', birth_year: 2026 }, now)).toBe('Child · under 1 year')
    expect(memberSubtitle({ relation: 'spouse', birth_year: null }, now)).toBe('Spouse')
  })
})

describe('validation', () => {
  it('needs a name and checks the optional fields', () => {
    expect(validateFamilyForm(EMPTY_FAMILY_FORM, now).name).toBeTruthy()
    expect(validateFamilyForm({ ...EMPTY_FAMILY_FORM, name: 'Asha' }, now)).toEqual({})
    expect(validateFamilyForm({ ...EMPTY_FAMILY_FORM, name: 'Asha', birthYear: '1850' }, now).birthYear).toBeTruthy()
    expect(validateFamilyForm({ ...EMPTY_FAMILY_FORM, name: 'Asha', birthYear: '2027' }, now).birthYear).toBeTruthy()
    expect(validateFamilyForm({ ...EMPTY_FAMILY_FORM, name: 'Asha', birthYear: '19x9' }, now).birthYear).toBeTruthy()
    expect(validateFamilyForm({ ...EMPTY_FAMILY_FORM, name: 'Asha', mobile: '12345' }, now).mobile).toBeTruthy()
    expect(validateFamilyForm({ ...EMPTY_FAMILY_FORM, name: 'Asha', mobile: '+91 98765 43210' }, now)).toEqual({})
  })
})

describe('request bodies', () => {
  it('create leaves empty optional fields out', () => {
    expect(familyCreateBody({ ...EMPTY_FAMILY_FORM, name: ' Asha ' })).toEqual({ name: 'Asha', relation: 'child' })
    expect(familyCreateBody({ name: 'Asha', relation: 'child', birthYear: '2019', gender: 'female', mobile: '98765 43210', language: 'te' })).toEqual({
      name: 'Asha',
      relation: 'child',
      birth_year: 2019,
      gender: 'female',
      mobile: '9876543210',
      language: 'te',
    })
  })

  it('patch sends null to clear a field', () => {
    expect(familyPatchBody({ ...EMPTY_FAMILY_FORM, name: 'Asha', relation: 'sibling' })).toEqual({ name: 'Asha', relation: 'sibling', birth_year: null, gender: null, mobile: null, language: null })
  })

  it('round-trips a member through the form', () => {
    expect(familyCreateBody(formFromMember(asha))).toEqual({ name: 'Asha Kumar', relation: 'child', birth_year: 2019, gender: 'female', mobile: '9876543210', language: 'te' })
  })
})

describe('booking for a member', () => {
  it('prefills patient fields from the member', () => {
    expect(bookingFieldsFor(asha, 'Me')).toEqual({ name: 'Asha Kumar', mobile: '9876543210', language: 'te' })
    expect(bookingFieldsFor({ ...asha, mobile: null, language: null }, 'Me')).toEqual({ name: 'Asha Kumar', mobile: '', language: null })
    expect(bookingFieldsFor(null, 'Ravi')).toEqual({ name: 'Ravi', mobile: '', language: null })
  })

  it('labels appointments booked for a member', () => {
    expect(forLabel({ name: 'Asha', relation: 'child' })).toBe('for Asha (child)')
    expect(forLabel({ name: 'Amma', relation: 'parent' })).toBe('for Amma (parent)')
    expect(forLabel(null)).toBeNull()
    expect(relationLabel('cousin')).toBe('Cousin')
  })
})
