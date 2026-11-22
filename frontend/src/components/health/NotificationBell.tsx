import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell, BellRing, CalendarCheck, CheckCheck, HeartPulse, MessageSquareHeart, Pill, Repeat, Syringe } from 'lucide-react'
import { useMarkAllNotificationsRead, useMarkNotificationRead, useNotifications, usePlannedRefs } from '@/api/hooks'
import type { AppNotification, NotificationKind } from '@/api/types'
import { ConfirmationBadge } from '@/components/health/shared'
import { useToast } from '@/components/ui/Toast'
import { useChat } from '@/hooks/ChatProvider'
import { cn, relativeTime } from '@/lib/format'
import { notificationPrefill, notificationTarget } from '@/lib/notifications'
import { Skeleton } from '@/components/ui/primitives'

const KIND_ICON: Record<NotificationKind, typeof Bell> = { appointment_reminder: CalendarCheck, follow_up: Repeat, feedback_request: MessageSquareHeart, medicine: Pill, symptom_checkin: HeartPulse, vaccine: Syringe }

export const OPEN_NOTIFICATIONS_EVENT = 'swasthya:open-notifications'

export function NotificationBell() {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const toast = useToast()
  const { startNew, setDraft } = useChat()
  const { data, isLoading, isError } = useNotifications()
  const markRead = useMarkNotificationRead()
  const planned = usePlannedRefs()
  const markAll = useMarkAllNotificationsRead()

  const unread = data?.unread_count ?? 0
  const items = data?.items ?? []

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => !root.current?.contains(e.target as Node) && setOpen(false)
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  // Other screens (the "Unread reminders" tile) can ask the bell to open.
  useEffect(() => {
    const onOpen = () => setOpen(true)
    window.addEventListener(OPEN_NOTIFICATIONS_EVENT, onOpen)
    return () => window.removeEventListener(OPEN_NOTIFICATIONS_EVENT, onOpen)
  }, [])

  const openItem = (n: AppNotification) => {
    setOpen(false)
    if (!n.read_at) markRead.mutate(n.id, { onError: () => undefined })
    const prefill = notificationPrefill(n)
    if (!n.conversation_id) startNew() // no thread to return to: begin a fresh one instead of the current chat
    if (prefill) setDraft(prefill)
    navigate(notificationTarget(n))
  }

  return (
    <div ref={root} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={unread > 0 ? `Notifications, ${unread} unread` : 'Notifications'}
        className="relative grid size-10 place-items-center rounded-xl text-muted transition hover:bg-soft hover:text-fg"
      >
        {unread > 0 ? <BellRing className="size-5 text-accent-text" /> : <Bell className="size-5" />}
        {unread > 0 && (
          <span className="absolute top-1 right-1 grid min-w-[1.1rem] place-items-center rounded-full bg-danger px-1 text-[10px] leading-[1.1rem] font-bold text-white" aria-hidden>
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div role="dialog" aria-label="Notifications" className="card absolute top-full right-0 z-50 mt-2 w-[min(92vw,24rem)] overflow-hidden shadow-[var(--shadow-pop)]">
          <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
            <h2 className="text-sm font-semibold">Notifications</h2>
            <button
              onClick={() => markAll.mutate(undefined, { onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not mark as read') })}
              disabled={unread === 0 || markAll.isPending}
              className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-accent-text transition hover:bg-accent-soft disabled:pointer-events-none disabled:opacity-40"
            >
              <CheckCheck className="size-3.5" aria-hidden /> Mark all read
            </button>
          </div>

          <div className="scroll-thin max-h-[60vh] overflow-y-auto">
            {isLoading ? (
              <div className="space-y-2 p-3">{[0, 1].map((i) => <Skeleton key={i} className="h-16" />)}</div>
            ) : isError ? (
              <p className="p-4 text-sm text-danger" role="alert">Could not load notifications.</p>
            ) : items.length === 0 ? (
              <div className="px-6 py-10 text-center text-sm text-muted">
                <Bell className="mx-auto mb-2 size-6 opacity-60" aria-hidden />
                No notifications yet. Reminders for your appointments will show up here.
              </div>
            ) : (
              <ul className="divide-y divide-line">
                {items.map((n) => {
                  const Icon = KIND_ICON[n.kind] ?? Bell
                  return (
                    <li key={n.id}>
                      <button onClick={() => openItem(n)} className={cn('flex w-full gap-3 px-4 py-3 text-left transition hover:bg-soft', !n.read_at && 'bg-accent-soft/40')}>
                        <span className={cn('mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg', n.read_at ? 'bg-soft text-muted' : 'bg-accent-soft text-accent-text')}>
                          <Icon className="size-4" aria-hidden />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-2">
                            <span className={cn('truncate text-sm', !n.read_at ? 'font-semibold' : 'font-medium')}>{n.title}</span>
                            {!n.read_at && <span className="size-2 shrink-0 rounded-full bg-accent" aria-label="Unread" />}
                          </span>
                          <span className="mt-0.5 line-clamp-3 text-sm break-words text-muted" lang={n.language}>{n.message}</span>
                          <span className="mt-1 block text-xs text-muted">
                            {n.appointment_ref && <span className="font-mono">{n.appointment_ref} · </span>}
                            {relativeTime(n.delivered_at)}
                          </span>
                          {n.appointment_ref && planned.has(n.appointment_ref) && <span className="mt-1.5 block"><ConfirmationBadge confirmed={false} /></span>}
                        </span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
