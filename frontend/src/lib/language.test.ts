import { describe, expect, it } from 'vitest'
import { AUTO_LANGUAGE, asrAvailable, findLanguage, languageLabel, languageToSend, nativeName, selectionLabel, speechLanguage, ttsAvailable } from './language'

describe('language helpers', () => {
  it('finds languages case-insensitively and by region code', () => {
    expect(findLanguage('TE')?.code).toBe('te')
    expect(findLanguage('hi-IN')?.code).toBe('hi')
    expect(findLanguage('xx')).toBeUndefined()
    expect(findLanguage(null)).toBeUndefined()
  })

  it('shows native names', () => {
    expect(nativeName('te')).toBe('తెలుగు')
    expect(nativeName('ta')).toBe('தமிழ்')
    expect(nativeName('zz')).toBe('zz')
    expect(languageLabel('hi')).toBe('हिन्दी · Hindi')
    expect(languageLabel('en')).toBe('English')
  })

  it('labels the auto option', () => {
    expect(selectionLabel(AUTO_LANGUAGE)).toBe('Auto-detect')
    expect(selectionLabel('kn')).toBe('ಕನ್ನಡ')
  })

  it('sends a language only when one is explicitly chosen', () => {
    expect(languageToSend(AUTO_LANGUAGE)).toBeUndefined()
    expect(languageToSend('te')).toBe('te')
  })

  it('picks the speech-recognition language: explicit > conversation > primary > en', () => {
    expect(speechLanguage('ta', 'hi', 'te')).toBe('ta')
    expect(speechLanguage(AUTO_LANGUAGE, 'hi', 'te')).toBe('hi')
    expect(speechLanguage(AUTO_LANGUAGE, null, 'te')).toBe('te')
    expect(speechLanguage(AUTO_LANGUAGE, undefined, undefined)).toBe('en')
  })

  it('reports voice availability from the list', () => {
    expect(ttsAvailable('te')).toBe(true)
    expect(ttsAvailable('ur')).toBe(false)
    expect(asrAvailable('ur')).toBe(true)
    expect(ttsAvailable('te', [{ code: 'te', name: 'Telugu', native_name: 'తెలుగు', asr: true, tts: false }])).toBe(false)
  })
})
