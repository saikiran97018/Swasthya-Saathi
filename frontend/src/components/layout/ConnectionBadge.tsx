import { useChat } from '@/hooks/ChatProvider'
import { cn } from '@/lib/format'

export function ConnectionBadge({ className }: { className?: string }) {
  const { connection, limitedMode } = useChat()
  const info =
    connection === 'open' && !limitedMode
      ? { dot: 'bg-ok', text: 'Live', hint: 'Connected in real time' }
      : limitedMode
        ? { dot: 'bg-saffron', text: 'Limited mode', hint: 'Real-time connection unavailable. Replies arrive all at once.' }
        : connection === 'closed'
          ? { dot: 'bg-danger', text: 'Offline', hint: 'Not connected to the server' }
          : { dot: 'bg-saffron animate-pulse', text: 'Connecting…', hint: 'Connecting to the server' }
  return (
    <span title={info.hint} role="status" className={cn('inline-flex items-center gap-1.5 text-xs text-muted', className)}>
      <span className={cn('size-2 rounded-full', info.dot)} aria-hidden />
      {info.text}
    </span>
  )
}
