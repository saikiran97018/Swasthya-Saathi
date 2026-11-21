import { useState } from 'react'
import { Check, ChevronDown, Sparkles } from 'lucide-react'
import { useLanguage } from '@/hooks/LanguageProvider'
import { useChooseLanguage, useDisplayLanguage } from '@/hooks/useChooseLanguage'
import { AUTO_LANGUAGE } from '@/lib/language'
import { cn } from '@/lib/format'
import { ToggleChip } from '@/components/ui/primitives'

/** The four languages shown as chips; every other language is behind "More". */
const PRIMARY = ['en', 'te', 'hi', 'ta']

/**
 * "Your language" row: English / తెలుగు / हिन्दी / தமிழ் and "More" (all 14 languages + auto-detect).
 * Choosing sets the app and conversation language (and saves it as the primary language).
 */
export function LanguageChips() {
  const { selected, languages } = useLanguage()
  const choose = useChooseLanguage()
  const current = useDisplayLanguage()
  const [more, setMore] = useState(false)

  const byCode = new Map(languages.map((l) => [l.code, l]))
  const chips = PRIMARY.map((c) => byCode.get(c)).filter((l): l is NonNullable<typeof l> => !!l)
  // A language picked from "More" stays visible as a chip so the current choice is never hidden.
  const extra = !PRIMARY.includes(current) ? byCode.get(current) : undefined
  const rest = languages.filter((l) => !PRIMARY.includes(l.code) && l.code !== extra?.code)

  return (
    <div>
      <div role="group" aria-label="Your language" className="flex flex-wrap gap-2">
        {[...chips, ...(extra ? [extra] : [])].map((l) => (
          <ToggleChip solid key={l.code} active={current === l.code} onClick={() => choose(l.code)} icon={current === l.code ? <Check className="size-4" aria-hidden /> : undefined}>
            {l.native_name}
          </ToggleChip>
        ))}
        <ToggleChip active={false} onClick={() => setMore((m) => !m)} icon={<ChevronDown className={cn('size-4 transition', more && 'rotate-180')} aria-hidden />}>
          More
        </ToggleChip>
      </div>

      {more && (
        <div className="mt-2 flex flex-wrap gap-2 rounded-2xl bg-soft/70 p-2.5" role="group" aria-label="More languages">
          <ToggleChip solid active={selected === AUTO_LANGUAGE} onClick={() => { choose(AUTO_LANGUAGE); setMore(false) }} icon={<Sparkles className="size-4" aria-hidden />}>
            Auto-detect
          </ToggleChip>
          {rest.map((l) => (
            <ToggleChip solid key={l.code} active={current === l.code} onClick={() => { choose(l.code); setMore(false) }}>
              {l.native_name}
              {l.native_name !== l.name && <span className="text-xs text-muted">{l.name}</span>}
            </ToggleChip>
          ))}
        </div>
      )}
    </div>
  )
}
