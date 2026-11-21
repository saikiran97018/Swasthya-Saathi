import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { useLanguages } from '@/api/hooks'
import type { LanguageInfo } from '@/api/types'
import { AUTO_LANGUAGE, FALLBACK_LANGUAGES, type LanguageSelection } from '@/lib/language'

const KEY = 'bva.language'

function readStored(): LanguageSelection {
  try {
    return localStorage.getItem(KEY) || AUTO_LANGUAGE
  } catch {
    return AUTO_LANGUAGE
  }
}

interface LanguageCtx {
  /** A language code the user picked, or AUTO_LANGUAGE. */
  selected: LanguageSelection
  setSelected: (s: LanguageSelection) => void
  languages: LanguageInfo[]
}

const Ctx = createContext<LanguageCtx | null>(null)

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [selected, setSelectedState] = useState<LanguageSelection>(readStored)
  const { data } = useLanguages()

  const setSelected = useCallback((s: LanguageSelection) => {
    setSelectedState(s)
    try {
      localStorage.setItem(KEY, s)
    } catch {
      /* ignore */
    }
  }, [])

  const value = useMemo(() => ({ selected, setSelected, languages: data ?? FALLBACK_LANGUAGES }), [selected, setSelected, data])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useLanguage(): LanguageCtx {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useLanguage must be used inside <LanguageProvider>')
  return ctx
}
