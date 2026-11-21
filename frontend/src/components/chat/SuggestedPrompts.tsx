import { motion } from 'framer-motion'
import { nativeName } from '@/lib/language'
import { SUGGESTED_PROMPTS, type SuggestedPrompt } from '@/lib/prompts'

export function SuggestedPrompts({ onPick, limit }: { onPick: (p: SuggestedPrompt) => void; limit?: number }) {
  const items = limit ? SUGGESTED_PROMPTS.slice(0, limit) : SUGGESTED_PROMPTS
  return (
    <ul className="grid gap-2 sm:grid-cols-2" aria-label="Suggested questions">
      {items.map((p, i) => (
        <motion.li key={p.text} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }}>
          <button
            onClick={() => onPick(p)}
            lang={p.lang}
            className="group card flex h-full w-full flex-col items-start gap-1.5 rounded-xl p-3.5 text-left transition hover:border-accent/50 hover:shadow-[var(--shadow-pop)]"
          >
            <span className="text-[15px] leading-snug font-medium">{p.text}</span>
            <span className="rounded-full bg-soft px-2 py-0.5 text-[11px] font-medium text-muted group-hover:bg-accent-soft group-hover:text-accent-text">{nativeName(p.lang)}</span>
          </button>
        </motion.li>
      ))}
    </ul>
  )
}
