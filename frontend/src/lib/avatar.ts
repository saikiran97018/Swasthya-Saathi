import { createAvatar } from '@dicebear/core'
import * as lorelei from '@dicebear/lorelei' // the standalone style packages export a namespace, not a named value

/**
 * Illustrated avatars for the (fictional, demo) doctors and clinics.
 * Generated locally, so the app works offline, nothing is fetched, and no real person's photo is ever used.
 * Style: DiceBear "Lorelei" by Lisa Wischofsky, artwork licensed CC0 1.0 (code MIT).
 */
const cache = new Map<string, string>()

const BACKGROUNDS = ['d6eeea', 'cfe5f2', 'fdefd0', 'e6e1f6', 'dcf0e2']

/** The same seed always gives the same picture (a data URI), so a provider keeps its face everywhere. */
export function avatarDataUri(seed: string): string {
  const key = seed.trim().toLowerCase() || 'swasthya-saathi'
  let uri = cache.get(key)
  if (!uri) {
    uri = createAvatar(lorelei, { seed: key, backgroundColor: BACKGROUNDS, backgroundType: ['solid'], radius: 50 }).toDataUri()
    cache.set(key, uri)
  }
  return uri
}

const TITLES = new Set(['dr', 'mr', 'mrs', 'ms', 'prof'])

/** "Dr. M. Khan (demo)" -> "MK", "Ravi Kumar" -> "RK", "" -> "?". Works for any script. */
export function initials(name: string | null | undefined): string {
  const words = (name ?? '')
    .replace(/\([^)]*\)/g, ' ')
    .split(/\s+/)
    .map((w) => w.replace(/[^\p{L}\p{M}]/gu, ''))
    .filter(Boolean)
  const meaningful = words.filter((w) => !TITLES.has(w.toLowerCase()))
  const use = (meaningful.length ? meaningful : words).slice(0, 2)
  const out = use.map((w) => Array.from(w)[0]).join('')
  return out ? out.toLocaleUpperCase() : '?'
}
