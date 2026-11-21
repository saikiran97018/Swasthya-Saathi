import type { FamilyGender, FamilyMember, FamilyMemberBody, FamilyRelation } from '@/api/types'
import { normalizeMobile } from './booking'

export const MAX_FAMILY_MEMBERS = 8

export const RELATION_LABEL: Record<FamilyRelation, string> = {
  self: 'Myself',
  spouse: 'Spouse',
  child: 'Child',
  parent: 'Parent',
  sibling: 'Brother or sister',
  other: 'Other',
}

export const GENDER_LABEL: Record<FamilyGender, string> = { female: 'Female', male: 'Male', other: 'Other' }

export const relationLabel = (r: string): string => RELATION_LABEL[r as FamilyRelation] ?? r.charAt(0).toUpperCase() + r.slice(1)

/** Age in whole years from a birth year (approximate: the year is all we store). */
export function ageFromBirthYear(birthYear: number | null | undefined, now: Date = new Date()): number | null {
  if (birthYear === null || birthYear === undefined) return null
  const age = now.getFullYear() - birthYear
  return age >= 0 && age <= 120 ? age : null
}

/** "Child · 7 years" for the list. */
export function memberSubtitle(m: Pick<FamilyMember, 'relation' | 'birth_year'>, now: Date = new Date()): string {
  const age = ageFromBirthYear(m.birth_year, now)
  const parts = [relationLabel(m.relation)]
  if (age !== null) parts.push(age === 0 ? 'under 1 year' : `${age} ${age === 1 ? 'year' : 'years'}`)
  return parts.join(' · ')
}

export interface FamilyForm {
  name: string
  relation: FamilyRelation
  birthYear: string
  gender: FamilyGender | ''
  mobile: string
  language: string
}

export const EMPTY_FAMILY_FORM: FamilyForm = { name: '', relation: 'child', birthYear: '', gender: '', mobile: '', language: '' }

export function formFromMember(m: FamilyMember): FamilyForm {
  return { name: m.name, relation: m.relation, birthYear: m.birth_year ? String(m.birth_year) : '', gender: m.gender ?? '', mobile: m.mobile ?? '', language: m.language ?? '' }
}

export type FamilyField = 'name' | 'birthYear' | 'mobile'

export function validateFamilyForm(f: FamilyForm, now: Date = new Date()): Partial<Record<FamilyField, string>> {
  const errors: Partial<Record<FamilyField, string>> = {}
  const name = f.name.trim()
  if (name.length < 2) errors.name = 'Enter a name (at least 2 letters).'
  else if (name.length > 80) errors.name = 'The name is too long (80 letters at most).'
  if (f.birthYear.trim()) {
    const y = Number(f.birthYear.trim())
    const max = now.getFullYear()
    if (!Number.isInteger(y) || y < max - 120 || y > max) errors.birthYear = `Enter a year between ${max - 120} and ${max}.`
  }
  if (f.mobile.trim() && !normalizeMobile(f.mobile)) errors.mobile = 'Enter a 10-digit mobile number starting with 6, 7, 8 or 9, or leave it empty.'
  return errors
}

/** Body for POST /family. Optional fields that are empty are left out. */
export function familyCreateBody(f: FamilyForm): FamilyMemberBody {
  const body: FamilyMemberBody = { name: f.name.trim(), relation: f.relation }
  if (f.birthYear.trim()) body.birth_year = Number(f.birthYear.trim())
  if (f.gender) body.gender = f.gender
  const mobile = f.mobile.trim() ? normalizeMobile(f.mobile) : null
  if (mobile) body.mobile = mobile
  if (f.language) body.language = f.language
  return body
}

/** Body for PATCH /family/{id}: empty optional fields are sent as null so they can be cleared. */
export function familyPatchBody(f: FamilyForm): Partial<FamilyMemberBody> {
  return {
    name: f.name.trim(),
    relation: f.relation,
    birth_year: f.birthYear.trim() ? Number(f.birthYear.trim()) : null,
    gender: f.gender || null,
    mobile: f.mobile.trim() ? normalizeMobile(f.mobile) : null,
    language: f.language || null,
  }
}

/** Choosing "Booking for" a member fills the patient fields. The mobile stays empty if the member has none. */
export function bookingFieldsFor(m: FamilyMember | null, fallbackName: string): { name: string; mobile: string; language: string | null } {
  if (!m) return { name: fallbackName, mobile: '', language: null }
  return { name: m.name, mobile: m.mobile ?? '', language: m.language }
}

/** "for Asha (child)" on an appointment card. */
export function forLabel(fm: { name: string; relation: string } | null | undefined): string | null {
  if (!fm) return null
  return `for ${fm.name} (${relationLabel(fm.relation).toLowerCase()})`
}
