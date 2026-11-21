const rtf = new Intl.RelativeTimeFormat('en-IN', { numeric: 'auto' })

export function relativeTime(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return ''
  const diff = new Date(iso).getTime() - now
  const abs = Math.abs(diff)
  const min = 60_000
  if (abs < min) return 'just now'
  if (abs < 60 * min) return rtf.format(Math.round(diff / min), 'minute')
  if (abs < 24 * 60 * min) return rtf.format(Math.round(diff / (60 * min)), 'hour')
  if (abs < 7 * 24 * 60 * min) return rtf.format(Math.round(diff / (24 * 60 * min)), 'day')
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' })
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
}

export function durationMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return ''
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`
}

/** "search_knowledge_base" -> "Search knowledge base" (fallback label for any tool name the backend sends). */
export function humanize(snake: string): string {
  const s = snake.replace(/[_-]+/g, ' ').trim()
  return s.charAt(0).toUpperCase() + s.slice(1)
}

const PROVIDER_KIND: Record<string, string> = { clinic: 'Clinic', hospital: 'Hospital', phc: 'Primary health centre', telemedicine: 'Video consultation service' }

/** "phc" -> "Primary health centre"; unknown kinds fall back to a humanized name. */
export function providerKindLabel(kind: string | null | undefined): string {
  if (!kind) return ''
  return PROVIDER_KIND[kind.toLowerCase()] ?? humanize(kind)
}

export function cn(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ')
}
