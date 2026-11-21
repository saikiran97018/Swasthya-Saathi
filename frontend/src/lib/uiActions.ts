import type { ToolExecution } from '@/api/types'

/** What the assistant can do to the screen (the backend tool `control_app`). Everything is validated again here. */
export type UiAction = { type: 'open_page'; path: string; label: string } | { type: 'set_theme'; theme: 'light' | 'dark' | 'system' }

/** The only pages an assistant instruction may open. Anything else (other sites, odd paths) is ignored. */
const PAGES = new Set(['/', '/chat', '/find-care', '/appointments', '/family', '/sos', '/history', '/activity', '/settings', '/settings/language', '/call'])
const THEMES = new Set(['light', 'dark', 'system'])
export const UI_ACTIONS_EVENT = 'swasthya:ui-actions'

/** A safe in-app path, or null. Only /find-care may carry a query, and only a short `city`. */
export function safePath(path: unknown): string | null {
  if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//') || path.includes('\\') || path.length > 140) return null
  const parts = path.split('?')
  const base = parts[0] ?? ''
  const query = parts[1]
  if (parts.length > 2 || !PAGES.has(base)) return null
  if (query === undefined) return base
  if (base !== '/find-care') return null
  const params = new URLSearchParams(query)
  const keys = [...params.keys()]
  const city = params.get('city')
  if (keys.length !== 1 || keys[0] !== 'city' || !city || city.length > 80 || /[<>]/.test(city)) return null
  return `${base}?city=${encodeURIComponent(city)}`
}

/** The action carried by a finished `control_app` tool run, or null if there is none or it is not valid. */
export function extractUiAction(exec: Pick<ToolExecution, 'tool_name' | 'status' | 'result'>): UiAction | null {
  if (exec.tool_name !== 'control_app' || exec.status !== 'success') return null
  const a = (exec.result as { ui_action?: Record<string, unknown> } | null)?.ui_action
  if (!a || typeof a !== 'object') return null
  if (a.type === 'open_page') {
    const path = safePath(a.path)
    return path ? { type: 'open_page', path, label: typeof a.label === 'string' ? a.label.slice(0, 40) : 'page' } : null
  }
  if (a.type === 'set_theme' && typeof a.theme === 'string' && THEMES.has(a.theme)) return { type: 'set_theme', theme: a.theme as 'light' | 'dark' | 'system' }
  return null
}

/** Opening an old conversation must not replay what the assistant did back then: only runs from about now count. */
export function isFresh(createdAt: string, mountedAt: number, graceMs = 15_000): boolean {
  const t = Date.parse(createdAt)
  return Number.isFinite(t) && t >= mountedAt - graceMs
}

/** Each tool run is carried out once, even if the same message is seen again (re-render, poll, reconnect). */
export function createClaimer(): (id: string) => boolean {
  const seen = new Set<string>()
  return (id) => (seen.has(id) ? false : (seen.add(id), true))
}

/** Actions to carry out now from a list of tool runs: valid, fresh, not done before, in order. */
export function actionsToRun(execs: readonly ToolExecution[], mountedAt: number, claim: (id: string) => boolean): UiAction[] {
  const out: UiAction[] = []
  for (const e of execs) {
    if (!isFresh(e.created_at, mountedAt)) continue
    const action = extractUiAction(e)
    if (action && claim(e.id)) out.push(action)
  }
  return out
}
