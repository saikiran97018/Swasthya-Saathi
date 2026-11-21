import type { LanguageInfo } from '@/api/types'

/** Fallback list used until GET /languages loads (and in tests). Mirrors backend/app/utils/language.py. */
export const FALLBACK_LANGUAGES: LanguageInfo[] = [
  { code: 'en', name: 'English', native_name: 'English', asr: true, tts: true },
  { code: 'hi', name: 'Hindi', native_name: 'हिन्दी', asr: true, tts: true },
  { code: 'te', name: 'Telugu', native_name: 'తెలుగు', asr: true, tts: true },
  { code: 'ta', name: 'Tamil', native_name: 'தமிழ்', asr: true, tts: true },
  { code: 'kn', name: 'Kannada', native_name: 'ಕನ್ನಡ', asr: true, tts: true },
  { code: 'ml', name: 'Malayalam', native_name: 'മലയാളം', asr: true, tts: true },
  { code: 'bn', name: 'Bengali', native_name: 'বাংলা', asr: true, tts: true },
  { code: 'mr', name: 'Marathi', native_name: 'मराठी', asr: true, tts: true },
  { code: 'gu', name: 'Gujarati', native_name: 'ગુજરાતી', asr: true, tts: true },
  { code: 'pa', name: 'Punjabi', native_name: 'ਪੰਜਾਬੀ', asr: true, tts: true },
  { code: 'or', name: 'Odia', native_name: 'ଓଡ଼ିଆ', asr: true, tts: true },
  { code: 'as', name: 'Assamese', native_name: 'অসমীয়া', asr: true, tts: true },
  { code: 'ur', name: 'Urdu', native_name: 'اردو', asr: true, tts: false },
  { code: 'sa', name: 'Sanskrit', native_name: 'संस्कृतम्', asr: true, tts: false },
]

/** The selector value meaning "let the app detect the language" (no `language` is sent to the backend). */
export const AUTO_LANGUAGE = 'auto'
export type LanguageSelection = string // a language code or AUTO_LANGUAGE

export function findLanguage(code: string | null | undefined, list: LanguageInfo[] = FALLBACK_LANGUAGES): LanguageInfo | undefined {
  if (!code) return undefined
  const base = code.toLowerCase().split(/[-_]/)[0]
  return list.find((l) => l.code === base)
}

/** Native name for display ("తెలుగు"); falls back to the code for unknown languages. */
export function nativeName(code: string | null | undefined, list?: LanguageInfo[]): string {
  return findLanguage(code, list)?.native_name ?? (code ?? '')
}

/** "తెలుగు · Telugu" style label, or just one name when they are the same (English). */
export function languageLabel(code: string | null | undefined, list?: LanguageInfo[]): string {
  const l = findLanguage(code, list)
  if (!l) return code ?? ''
  return l.native_name === l.name ? l.name : `${l.native_name} · ${l.name}`
}

export function selectionLabel(selection: LanguageSelection, list?: LanguageInfo[]): string {
  return selection === AUTO_LANGUAGE ? 'Auto-detect' : nativeName(selection, list)
}

/** The language to send with a chat message: only a concrete choice is sent, "auto" sends nothing. */
export function languageToSend(selection: LanguageSelection): string | undefined {
  return selection === AUTO_LANGUAGE ? undefined : selection
}

/**
 * Language used for speech recognition. A concrete selection wins; with auto-detect we use the
 * conversation's language if it has one, otherwise the user's primary language.
 */
export function speechLanguage(selection: LanguageSelection, conversationLanguage: string | null | undefined, primary: string | undefined): string {
  if (selection !== AUTO_LANGUAGE) return selection
  return conversationLanguage || primary || 'en'
}

export function ttsAvailable(code: string | null | undefined, list?: LanguageInfo[]): boolean {
  return findLanguage(code, list)?.tts ?? false
}

export function asrAvailable(code: string | null | undefined, list?: LanguageInfo[]): boolean {
  return findLanguage(code, list)?.asr ?? false
}
