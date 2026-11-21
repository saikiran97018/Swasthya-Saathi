import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import type { ToolExecution } from '@/api/types'
import { useToast } from '@/components/ui/Toast'
import { useChat } from '@/hooks/ChatProvider'
import { useTheme } from '@/hooks/ThemeProvider'
import { actionsToRun, createClaimer, UI_ACTIONS_EVENT } from '@/lib/uiActions'

const THEME_TEXT = { light: 'Light theme on', dark: 'Dark theme on', system: 'Theme now follows your device' } as const

/**
 * Carries out what the assistant asks of the screen ("open the doctors page", "dark mode") from the `control_app` tool,
 * wherever the conversation happens: the chat and voice screens (messages in the chat state) and a live call (the call
 * transcript sends its polled tool runs as an event). Old messages are never replayed, and each run happens once.
 * During a live call, leaving the call page would hang up, so the person is asked first.
 */
export function UiActionRunner() {
  const { state } = useChat()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { setTheme } = useTheme()
  const toast = useToast()
  const mountedAt = useRef(Date.now())
  const claim = useRef(createClaimer())
  const where = useRef(pathname)
  where.current = pathname
  const [offer, setOffer] = useState<{ path: string; label: string } | null>(null)

  const apply = useCallback(
    (execs: readonly ToolExecution[]) => {
      for (const action of actionsToRun(execs, mountedAt.current, claim.current)) {
        if (action.type === 'set_theme') {
          setTheme(action.theme)
          toast.success(THEME_TEXT[action.theme])
        } else if (where.current === '/call' && action.path.split('?')[0] !== '/call') {
          setOffer({ path: action.path, label: action.label }) // opening another page now would end the call
        } else {
          navigate(action.path)
          toast.info(`Opened ${action.label}`)
        }
      }
    },
    [navigate, setTheme, toast],
  )

  useEffect(() => {
    apply(state.messages.flatMap((m) => m.tool_executions))
  }, [state.messages, apply])

  useEffect(() => {
    const onEvent = (e: Event) => apply((e as CustomEvent<ToolExecution[]>).detail ?? [])
    window.addEventListener(UI_ACTIONS_EVENT, onEvent)
    return () => window.removeEventListener(UI_ACTIONS_EVENT, onEvent)
  }, [apply])

  useEffect(() => {
    if (pathname !== '/call') setOffer(null)
  }, [pathname])

  if (!offer) return null
  return (
    <div role="alertdialog" aria-label={`Open ${offer.label}?`} className="fixed inset-x-3 bottom-24 z-50 mx-auto flex max-w-md flex-wrap items-center gap-3 rounded-2xl border border-line bg-elev p-3.5 shadow-lg md:bottom-6">
      <p className="min-w-0 flex-1 text-sm">The assistant wants to open <strong>{offer.label}</strong>. That ends your call.</p>
      <div className="flex gap-2">
        <button type="button" onClick={() => setOffer(null)} className="inline-flex min-h-11 items-center rounded-xl px-3 text-sm font-semibold text-muted hover:bg-soft">Not now</button>
        <button
          type="button"
          onClick={() => {
            navigate(offer.path)
            setOffer(null)
          }}
          className="inline-flex min-h-11 items-center rounded-xl bg-accent px-4 text-sm font-semibold text-accent-fg hover:brightness-110"
        >
          Open
        </button>
      </div>
    </div>
  )
}
