import { useEffect, useState } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { Activity, ChevronDown, ChevronRight } from 'lucide-react'
import { useMe } from '@/api/hooks'
import { useChat } from '@/hooks/ChatProvider'
import { InitialsBadge } from '@/components/health/Avatars'
import { cn } from '@/lib/format'
import { Brand } from './Brand'
import { ConnectionBadge } from './ConnectionBadge'
import { LanguageSelector } from './LanguageSelector'
import { NAV_ITEMS, isActive, resolveTo, type NavItem } from './nav'

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { state, startNew } = useChat()
  const { data: me } = useMe()

  const mainItems = NAV_ITEMS.filter((i) => i.group === 'main')
  const moreItems = NAV_ITEMS.filter((i) => i.group === 'more')
  const moreActive = moreItems.some((i) => isActive(i, pathname))
  // "More" is collapsed by default and opens by itself when you are on one of its screens.
  const [moreOpen, setMoreOpen] = useState(moreActive)
  useEffect(() => {
    if (moreActive) setMoreOpen(true)
  }, [moreActive])

  const newConversation = () => {
    startNew()
    navigate('/chat')
    onNavigate?.()
  }

  const link = (item: NavItem) => {
    const Icon = item.icon
    const active = isActive(item, pathname)
    return (
      <NavLink
        key={item.key}
        to={resolveTo(item, state.conversationId)}
        onClick={onNavigate}
        aria-current={active ? 'page' : undefined}
        className={cn(
          'relative flex h-11 items-center gap-3 rounded-xl px-3 text-sm font-medium transition',
          active ? 'bg-accent-soft font-semibold text-accent-text' : 'text-fg hover:bg-soft',
        )}
      >
        {active && <span aria-hidden className="absolute top-2 bottom-2 left-0 w-1 rounded-full bg-accent" />}
        <Icon className={cn('size-5', active ? 'text-accent-text' : 'text-fg/80')} aria-hidden />
        {item.label}
      </NavLink>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* This part scrolls on its own; the account footer below is pinned, so the two can never overlap. */}
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-3.5 pb-3 scroll-thin">
        <Link to="/" onClick={onNavigate} aria-label="Swasthya Saathi home" className="rounded-xl px-1 pt-1">
          <Brand />
        </Link>

        <button
          onClick={newConversation}
          className="flex h-12 shrink-0 items-center justify-center gap-2 rounded-full bg-accent px-4 text-sm font-semibold text-accent-fg shadow-sm transition hover:brightness-110 active:scale-[0.98]"
        >
          <Activity className="size-[18px]" aria-hidden /> New Conversation
        </button>

        <nav aria-label="Main" className="flex shrink-0 flex-col gap-1">
          {mainItems.map(link)}
          <button
            type="button"
            onClick={() => setMoreOpen((o) => !o)}
            aria-expanded={moreOpen}
            aria-controls="sidebar-more"
            className="flex h-10 items-center gap-3 rounded-xl px-3 text-sm font-medium text-muted transition hover:bg-soft hover:text-fg"
          >
            <ChevronDown className={cn('size-5 transition', moreOpen && 'rotate-180')} aria-hidden />
            More
          </button>
          {moreOpen && (
            <div id="sidebar-more" className="flex flex-col gap-0.5 border-l border-line pl-2">
              {moreItems.map(link)}
            </div>
          )}
        </nav>
      </div>

      <div className="shrink-0 space-y-2.5 border-t border-line p-3.5 pt-3">
        <LanguageSelector />
        <Link to="/settings" onClick={onNavigate} className="flex min-w-0 items-center gap-2.5 rounded-2xl p-1.5 transition hover:bg-soft" aria-label="Profile and settings">
          <InitialsBadge name={me?.display_name} size={40} />
          <span className="min-w-0 flex-1 leading-tight">
            <span className="block truncate text-sm font-semibold">{me?.display_name ?? '…'}</span>
            <span className="block truncate text-xs text-muted">{me?.is_guest ? 'Guest account' : 'Your account'}</span>
          </span>
          <ChevronRight className="size-4 shrink-0 text-muted" aria-hidden />
        </Link>
        <ConnectionBadge className="px-1.5" />
      </div>
    </div>
  )
}
