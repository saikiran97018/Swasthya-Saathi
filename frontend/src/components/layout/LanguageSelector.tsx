import { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, Globe } from 'lucide-react'
import { AUTO_LANGUAGE, nativeName, selectionLabel } from '@/lib/language'
import { cn } from '@/lib/format'
import { useChooseLanguage, useDisplayLanguage } from '@/hooks/useChooseLanguage'
import { useLanguage } from '@/hooks/LanguageProvider'

/** "EN", "TE"... for the compact header pill. */
export function shortLanguageCode(selected: string): string {
  return selected.toUpperCase()
}

/**
 * Language picker. "Auto-detect" sends no language to the backend (it detects from the script and keeps
 * the conversation language); a concrete choice is sent with every message until changed.
 * `variant="pill"` is the compact globe + code button used in the header.
 */
export function LanguageSelector({ className, direction = 'up', variant = 'field' }: { className?: string; direction?: 'up' | 'down'; variant?: 'field' | 'pill' }) {
  const { selected, languages } = useLanguage()
  const choose = useChooseLanguage()
  const display = useDisplayLanguage()
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)

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

  const pick = (code: string) => {
    choose(code)
    setOpen(false)
  }
  const pill = variant === 'pill'

  return (
    <div ref={root} className={cn('relative', className)}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Language: ${selectionLabel(selected, languages)}. Change language`}
        className={cn(
          'flex items-center gap-1.5 transition',
          pill ? 'h-10 justify-center rounded-full border border-line bg-elev px-3 text-xs font-bold tracking-wide hover:bg-soft' : 'h-12 w-full gap-2 rounded-2xl border border-line bg-elev px-3.5 text-sm hover:bg-soft',
        )}
      >
        {pill ? <Globe className="size-4 text-accent-text" aria-hidden /> : <Globe className="size-[18px] text-fg" aria-hidden />}
        {pill ? (
          <>
            <span>{shortLanguageCode(display)}</span>
            <ChevronDown className={cn('hidden size-3.5 text-muted transition sm:block', open && 'rotate-180')} aria-hidden />
          </>
        ) : (
          <>
            <span className="min-w-0 flex-1 truncate text-left font-medium">{nativeName(display, languages)}</span>
            <ChevronDown className={cn('size-4 text-muted transition', open && 'rotate-180')} aria-hidden />
          </>
        )}
      </button>

      {open && (
        <ul
          role="listbox"
          aria-label="Languages"
          className={cn(
            'scroll-thin card absolute z-50 max-h-72 min-w-56 overflow-y-auto p-1.5 shadow-[var(--shadow-pop)]',
            pill ? 'right-0 w-64' : 'w-full',
            direction === 'up' ? 'bottom-full mb-2' : 'top-full mt-2',
          )}
        >
          <Option active={selected === AUTO_LANGUAGE} onClick={() => pick(AUTO_LANGUAGE)} primary="Auto-detect" secondary="Follow the language you speak or type" />
          {languages.map((l) => (
            <Option key={l.code} active={selected === l.code} onClick={() => pick(l.code)} primary={l.native_name} secondary={l.native_name === l.name ? undefined : l.name} hint={!l.tts ? 'Text only' : undefined} />
          ))}
        </ul>
      )}
    </div>
  )
}

function Option({ active, onClick, primary, secondary, hint }: { active: boolean; onClick: () => void; primary: string; secondary?: string; hint?: string }) {
  return (
    <li role="option" aria-selected={active}>
      <button onClick={onClick} className={cn('flex min-h-11 w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-sm transition hover:bg-soft', active && 'bg-accent-soft')}>
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium">{primary}</span>
          {secondary && <span className="block truncate text-xs text-muted">{secondary}</span>}
        </span>
        {hint && <span className="shrink-0 rounded-full bg-soft px-1.5 py-0.5 text-[10px] font-medium text-muted">{hint}</span>}
        {active && <Check className="size-4 shrink-0 text-accent-text" />}
      </button>
    </li>
  )
}
