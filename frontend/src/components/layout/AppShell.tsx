import { useEffect, useState, type ReactNode } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { HeartPulse, X } from 'lucide-react'
import { useMe } from '@/api/hooks'
import { useChat } from '@/hooks/ChatProvider'
import { cn } from '@/lib/format'
import { ErrorBoundary } from '@/components/ui/ErrorBoundary'
import { IconButton } from '@/components/ui/primitives'
import { InitialsBadge } from '@/components/health/Avatars'
import { NotificationBell } from '@/components/health/NotificationBell'
import { LogoMark, SosButton } from './Brand'
import { LanguageSelector } from './LanguageSelector'
import { Sidebar } from './Sidebar'
import { NAV_ITEMS, isActive, resolveTo, screenSubtitle } from './nav'

export function AppShell({ children }: { children: ReactNode }) {
  const [drawer, setDrawer] = useState(false)
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { state } = useChat()
  const { data: me } = useMe()

  // Close the menu sheet on navigation; Escape closes it too.
  useEffect(() => setDrawer(false), [pathname])
  useEffect(() => {
    if (!drawer) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setDrawer(false)
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [drawer])

  // Ctrl/Cmd+K: jump to conversation search.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        navigate('/history', { state: { focusSearch: Date.now() } })
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [navigate])

  const bottomItems = NAV_ITEMS.filter((i) => i.bottom)
  const subtitle = screenSubtitle(pathname)

  return (
    <div className="flex h-dvh overflow-hidden">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[200] focus:rounded-lg focus:bg-elev focus:px-3 focus:py-2 focus:shadow-lg">
        Skip to content
      </a>

      {/* desktop sidebar */}
      <aside className="hidden w-52 shrink-0 border-r border-line bg-elev lg:block xl:w-56" aria-label="Sidebar">
        <Sidebar />
      </aside>

      {/* mobile menu sheet (opened from the avatar): history, activity, voice, language, settings */}
      <AnimatePresence>
        {drawer && (
          <div className="fixed inset-0 z-[80] lg:hidden">
            <motion.div className="absolute inset-0 bg-black/50" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setDrawer(false)} />
            <motion.aside
              role="dialog"
              aria-modal="true"
              aria-label="Menu"
              className="absolute inset-y-0 right-0 w-[19rem] max-w-[88vw] border-l border-line bg-elev shadow-[var(--shadow-pop)]"
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ type: 'spring', stiffness: 380, damping: 38 }}
            >
              <IconButton label="Close menu" size="sm" className="absolute top-3 right-3 z-10" onClick={() => setDrawer(false)}>
                <X className="size-4" />
              </IconButton>
              <Sidebar onNavigate={() => setDrawer(false)} />
            </motion.aside>
          </div>
        )}
      </AnimatePresence>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 shrink-0 items-center gap-1 border-b border-line bg-elev/90 px-3 backdrop-blur lg:h-[4.25rem] lg:gap-3 lg:px-6">
          {/* mobile: logo + screen subtitle */}
          <Link to="/" aria-label="Swasthya Saathi, home" className="flex min-w-0 flex-1 items-center gap-2 lg:hidden">
            <LogoMark className="size-9" />
            <span className="min-w-0 leading-tight">
              <span className="block truncate text-[13px] font-bold tracking-tight text-accent-text">Swasthya Saathi</span>
              <span className="block truncate text-[11px] text-muted">{subtitle}</span>
            </span>
          </Link>
          {/* desktop: the sidebar carries the brand, so the header names the screen */}
          <div className="hidden min-w-0 flex-1 items-center gap-2.5 lg:flex">
            <HeartPulse className="size-6 shrink-0 text-accent" aria-hidden />
            <span className="truncate text-[15px] font-semibold">{subtitle}</span>
          </div>

          <SosButton className="mr-0.5" />
          <NotificationBell />
          <LanguageSelector variant="pill" direction="down" />

          <button onClick={() => setDrawer(true)} aria-label="Open menu" aria-haspopup="dialog" className="grid size-10 shrink-0 place-items-center rounded-full lg:hidden">
            <InitialsBadge name={me?.display_name} size={36} />
          </button>
          <Link to="/settings" aria-label="Profile and settings" className="hidden shrink-0 rounded-full lg:block">
            <InitialsBadge name={me?.display_name} size={36} />
          </Link>
        </header>

        <main id="main" className="min-h-0 flex-1 overflow-y-auto scroll-thin" tabIndex={-1}>
          <ErrorBoundary resetKey={pathname}>{children}</ErrorBoundary>
        </main>

        {/* mobile bottom navigation: Triage, AI Consult, Doctors, Care Plan */}
        <nav aria-label="Primary" className="grid shrink-0 grid-cols-4 border-t border-line bg-elev pb-[env(safe-area-inset-bottom)] lg:hidden">
          {bottomItems.map((item) => {
            const Icon = item.icon
            const active = isActive(item, pathname)
            return (
              <NavLink
                key={item.key}
                to={resolveTo(item, state.conversationId)}
                aria-current={active ? 'page' : undefined}
                className={cn('flex min-h-14 flex-col items-center justify-center gap-0.5 py-1.5 text-[11px] font-semibold transition', active ? 'text-accent-text' : 'text-muted')}
              >
                <span className={cn('grid h-7 w-14 place-items-center rounded-full transition', active && 'bg-accent-soft')}>
                  <Icon className="size-5" aria-hidden />
                </span>
                {item.label}
              </NavLink>
            )
          })}
        </nav>
      </div>
    </div>
  )
}
