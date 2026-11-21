import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useUpdatePrefs } from '@/api/hooks'
import type { Preferences } from '@/api/types'

type Theme = Preferences['theme']
const KEY = 'bva.theme'

function readStored(): Theme {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' || v === 'system' ? v : 'light'
  } catch {
    return 'light'
  }
}

function apply(theme: Theme) {
  const dark = theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.classList.toggle('dark', dark)
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#0a1514' : '#edf5f3')
}

interface ThemeCtx {
  theme: Theme
  setTheme: (t: Theme) => void
}
const Ctx = createContext<ThemeCtx | null>(null)

/** Theme is applied instantly from localStorage (no flash) and mirrored to the server preference. */
export function ThemeProvider({ children, serverTheme }: { children: ReactNode; serverTheme?: Theme }) {
  const [theme, setThemeState] = useState<Theme>(readStored)
  const update = useUpdatePrefs()

  useEffect(() => {
    // Light is the default look. Only an explicit light/dark choice saved on the server is adopted
    // (the server's "system" default would otherwise flip a light-first app to dark on dark-mode devices).
    if (serverTheme && serverTheme !== 'system' && serverTheme !== theme && localStorage.getItem(KEY) === null) setThemeState(serverTheme)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverTheme])

  useEffect(() => {
    apply(theme)
    if (theme !== 'system') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => apply('system')
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [theme])

  const setTheme = useCallback(
    (t: Theme) => {
      setThemeState(t)
      try {
        localStorage.setItem(KEY, t)
      } catch {
        /* ignore */
      }
      update.mutate({ theme: t })
    },
    [update],
  )

  const value = useMemo(() => ({ theme, setTheme }), [theme, setTheme])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useTheme must be used inside <ThemeProvider>')
  return ctx
}
