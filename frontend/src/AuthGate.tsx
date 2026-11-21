import { type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { MotionConfig } from 'framer-motion'
import { ensureToken } from '@/api/client'
import { usePrefs } from '@/api/hooks'
import { LogoMark } from '@/components/layout/Brand'
import { Button } from '@/components/ui/primitives'
import { ThemeProvider } from '@/hooks/ThemeProvider'

/**
 * Creates the guest account on first visit and only renders the app once we hold a token,
 * so every screen can assume it is signed in. Shows a friendly retry if the backend is down.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const boot = useQuery({ queryKey: ['bootstrap'], queryFn: ensureToken, staleTime: Infinity, retry: 1, retryDelay: 800 })

  if (boot.isError) {
    return (
      <div role="alert" className="grid min-h-dvh place-items-center p-6 text-center">
        <div className="max-w-sm">
          <LogoMark className="mx-auto mb-4 size-14" />
          <h1 className="text-xl font-semibold">Can't reach Swasthya Saathi</h1>
          <p className="mt-2 text-muted">{boot.error instanceof Error ? boot.error.message : 'The server is not responding.'} Make sure the backend is running, then try again.</p>
          <Button variant="primary" className="mt-5" onClick={() => void boot.refetch()}>Try again</Button>
          <div className="mt-8 rounded-2xl border border-danger/30 bg-danger-soft p-4">
            <p className="text-sm font-semibold text-danger">In an emergency you do not need the app</p>
            <div className="mt-3 grid grid-cols-2 gap-2.5">
              <a href="tel:112" className="flex h-12 items-center justify-center rounded-2xl bg-danger font-bold text-white">Call 112</a>
              <a href="tel:108" className="flex h-12 items-center justify-center rounded-2xl border-2 border-danger bg-elev font-bold text-danger">Call 108</a>
            </div>
            <p className="mt-2 text-xs text-muted">112 is the national emergency number, 108 is an ambulance.</p>
          </div>
        </div>
      </div>
    )
  }
  if (!boot.isSuccess) {
    return (
      <div className="grid min-h-dvh place-items-center" aria-busy aria-label="Starting">
        <LogoMark className="anim-breathe size-14" />
      </div>
    )
  }
  return <Themed>{children}</Themed>
}

function Themed({ children }: { children: ReactNode }) {
  const { data } = usePrefs()
  return (
    <ThemeProvider serverTheme={data?.theme}>
      <MotionConfig reducedMotion="user">{children}</MotionConfig>
    </ThemeProvider>
  )
}
