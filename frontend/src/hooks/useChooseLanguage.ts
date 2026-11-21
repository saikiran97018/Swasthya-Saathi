import { useCallback } from 'react'
import { usePrefs, useUpdatePrefs } from '@/api/hooks'
import { AUTO_LANGUAGE } from '@/lib/language'
import { useLanguage } from './LanguageProvider'

/**
 * Pick the app/conversation language. A concrete language is also saved as the person's primary language
 * (PUT /preferences), so new conversations start in it; "auto" only changes the local selection.
 */
export function useChooseLanguage() {
  const { setSelected } = useLanguage()
  const { data: prefs } = usePrefs()
  const update = useUpdatePrefs()
  const primary = prefs?.primary_language

  return useCallback(
    (code: string) => {
      setSelected(code)
      if (code !== AUTO_LANGUAGE && code !== primary) update.mutate({ primary_language: code })
    },
    [setSelected, update, primary],
  )
}

/**
 * The language to show as "current" in chips and the header pill. With auto-detect on, that is the person's
 * saved primary language (new conversations start in it), so the UI never shows nothing selected.
 */
export function useDisplayLanguage(): string {
  const { selected } = useLanguage()
  const { data: prefs } = usePrefs()
  return selected === AUTO_LANGUAGE ? (prefs?.primary_language || 'en') : selected
}
