import { ClipboardList, History, Languages, MessageSquareText, House, Phone, Settings, UserRoundSearch, Users, Activity, Pill, Route as RouteIcon, Sparkles, Syringe, type LucideIcon } from 'lucide-react'

export interface NavItem {
  key: string
  label: string
  icon: LucideIcon
  /** Static path, or a function of the active conversation id (voice/chat keep the current thread). */
  to: string | ((conversationId: string | null) => string)
  end?: boolean
  /** Path prefix that marks this item active. */
  match: string
  /** Show in the mobile bottom bar (exactly the four main screens). */
  bottom?: boolean
  /** "main" screens come first in the sidebar; "more" sit under their own heading. */
  group: 'main' | 'more'
  /** Shown under the brand name in the header ("Intake & Triage"). */
  subtitle: string
}

/** Single place to add screens, so the sidebar, the menu sheet and the mobile bottom bar stay in sync. */
export const NAV_ITEMS: NavItem[] = [
  { key: 'home', label: 'Home', icon: House, to: '/', end: true, match: '/', bottom: true, group: 'main', subtitle: 'Your health guide' },
  { key: 'chat', label: 'AI Consult', icon: MessageSquareText, to: (id) => (id ? `/chat/${id}` : '/chat'), match: '/chat', bottom: true, group: 'main', subtitle: 'AI Consult' },
  { key: 'doctors', label: 'Doctors', icon: UserRoundSearch, to: '/find-care', match: '/find-care', bottom: true, group: 'main', subtitle: 'Booking & Doctors' },
  { key: 'careplan', label: 'Care Plan', icon: ClipboardList, to: '/appointments', match: '/appointments', bottom: true, group: 'main', subtitle: 'Care Plan' },
  { key: 'family', label: 'Family', icon: Users, to: '/family', match: '/family', group: 'more', subtitle: 'Family profiles' },
  { key: 'call', label: 'Live call', icon: Phone, to: '/call', match: '/call', group: 'more', subtitle: 'Live voice call' },
  { key: 'medicines', label: 'Medicines', icon: Pill, to: '/medicines', match: '/medicines', group: 'more', subtitle: 'Medicine reminders' },
  { key: 'vaccines', label: 'Vaccines', icon: Syringe, to: '/vaccines', match: '/vaccines', group: 'more', subtitle: 'Child vaccination tracker' },
  { key: 'timeline', label: 'Timeline', icon: RouteIcon, to: '/timeline', match: '/timeline', group: 'more', subtitle: 'Your health timeline' },
  { key: 'plans', label: 'Saathi Plus', icon: Sparkles, to: '/plans', match: '/plans', group: 'more', subtitle: 'Plans and billing' },
  { key: 'history', label: 'History', icon: History, to: '/history', match: '/history', group: 'more', subtitle: 'Conversation history' },
  { key: 'activity', label: 'Activity', icon: Activity, to: '/activity', match: '/activity', group: 'more', subtitle: 'What your assistant did' },
  { key: 'language', label: 'Language', icon: Languages, to: '/settings/language', match: '/settings/language', group: 'more', subtitle: 'Language settings' },
  { key: 'settings', label: 'Settings', icon: Settings, to: '/settings', end: true, match: '/settings', group: 'more', subtitle: 'Settings' },
]

export function resolveTo(item: NavItem, conversationId: string | null): string {
  return typeof item.to === 'function' ? item.to(conversationId) : item.to
}

export function isActive(item: NavItem, pathname: string): boolean {
  if (item.end) return pathname === item.match
  return pathname === item.match || pathname.startsWith(item.match + '/')
}

/** The header subtitle for the current screen: the longest matching nav entry wins ("/settings/language" over "/settings"). */
/** Screens that are not in the menus (the SOS page is opened from the header button only). */
const EXTRA_SUBTITLES: Record<string, string> = { '/sos': 'Emergency help' }

export function screenSubtitle(pathname: string): string {
  if (EXTRA_SUBTITLES[pathname]) return EXTRA_SUBTITLES[pathname]
  const hit = [...NAV_ITEMS].filter((i) => isActive(i, pathname)).sort((a, b) => b.match.length - a.match.length)[0]
  return hit?.subtitle ?? 'Your health guide'
}
