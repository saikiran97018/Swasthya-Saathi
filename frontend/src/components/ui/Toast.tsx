import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { CircleAlert, CircleCheck, Info, X } from 'lucide-react'
import { cn } from '@/lib/format'

type ToastKind = 'error' | 'success' | 'info'
interface ToastItem {
  id: number
  kind: ToastKind
  message: string
}

interface ToastApi {
  error: (message: string) => void
  success: (message: string) => void
  info: (message: string) => void
}

const ToastContext = createContext<ToastApi | null>(null)

const STYLE: Record<ToastKind, string> = {
  error: 'border-danger/40 bg-danger-soft text-danger',
  success: 'border-ok/40 bg-ok-soft text-ok',
  info: 'border-line bg-elev text-fg',
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const nextId = useRef(1)

  const dismiss = useCallback((id: number) => setItems((cur) => cur.filter((t) => t.id !== id)), [])
  const push = useCallback(
    (kind: ToastKind, message: string) => {
      const id = nextId.current++
      setItems((cur) => [...cur.filter((t) => t.message !== message).slice(-3), { id, kind, message }])
      window.setTimeout(() => dismiss(id), kind === 'success' ? 4000 : 8000)
    },
    [dismiss],
  )
  const api = useMemo<ToastApi>(() => ({ error: (m) => push('error', m), success: (m) => push('success', m), info: (m) => push('info', m) }), [push])

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div aria-live="polite" role="status" className="pointer-events-none fixed inset-x-0 bottom-20 z-[100] flex flex-col items-center gap-2 px-4 md:bottom-6">
        <AnimatePresence initial={false}>
          {items.map((t) => (
            <motion.div
              key={t.id}
              layout
              initial={{ opacity: 0, y: 16, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 8, scale: 0.97 }}
              className={cn('pointer-events-auto flex max-w-md items-start gap-2.5 rounded-xl border px-3.5 py-2.5 text-sm shadow-[var(--shadow-pop)]', STYLE[t.kind])}
            >
              {t.kind === 'error' ? <CircleAlert className="mt-0.5 size-4 shrink-0" /> : t.kind === 'success' ? <CircleCheck className="mt-0.5 size-4 shrink-0" /> : <Info className="mt-0.5 size-4 shrink-0" />}
              <span className="min-w-0 flex-1 break-words text-fg">{t.message}</span>
              <button aria-label="Dismiss notification" onClick={() => dismiss(t.id)} className="-m-1 rounded p-1 text-muted hover:text-fg">
                <X className="size-3.5" />
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>')
  return ctx
}
