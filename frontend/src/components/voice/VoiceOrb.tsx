import { motion } from 'framer-motion'
import { AudioLines, LoaderCircle, Mic, MicOff, Square, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/format'

export type OrbState = 'idle' | 'listening' | 'processing' | 'speaking' | 'muted'

interface Props {
  state: OrbState
  /** Mic loudness 0..1 while listening. */
  level: number
  onClick: () => void
  disabled?: boolean
  label: string
  /** Replaces the stop-square shown while listening (the live call uses a mic, since tapping mutes). */
  listeningIcon?: LucideIcon
}

/**
 * The big voice button. Each state has its own motion:
 *  idle        slow breathing glow
 *  listening   core and ring scale with the loudness of the user's voice
 *  processing  a rotating arc around a pulsing core
 *  speaking    ripples radiating outward
 *  muted       desaturated, still
 */
export function VoiceOrb({ state, level, onClick, disabled, label, listeningIcon }: Props) {
  const scale = state === 'listening' ? 1 + Math.min(1, level) * 0.2 : 1
  const Icon = state === 'listening' ? (listeningIcon ?? Square) : state === 'speaking' ? AudioLines : state === 'muted' ? MicOff : state === 'processing' ? LoaderCircle : Mic

  return (
    <div className="relative grid size-56 place-items-center sm:size-64">
      {/* outer glow */}
      <div
        aria-hidden
        className={cn(
          'absolute inset-4 rounded-full blur-2xl transition-opacity duration-500',
          state === 'muted' ? 'opacity-20' : 'opacity-60',
          state === 'idle' && 'anim-breathe',
        )}
        style={{ background: 'radial-gradient(circle, var(--accent) 0%, color-mix(in srgb, var(--saffron) 60%, transparent) 55%, transparent 75%)' }}
      />

      {/* speaking: ripples */}
      {state === 'speaking' &&
        [0, 0.8, 1.6].map((d) => (
          <span key={d} aria-hidden className="anim-ripple absolute size-32 rounded-full border-2 border-accent sm:size-36" style={{ animationDelay: `${d}s` }} />
        ))}

      {/* listening: loudness ring */}
      {state === 'listening' && (
        <motion.span
          aria-hidden
          className="absolute size-32 rounded-full border-2 border-accent sm:size-36"
          animate={{ scale: 1.15 + level * 0.9, opacity: 0.25 + level * 0.5 }}
          transition={{ type: 'spring', stiffness: 220, damping: 18 }}
        />
      )}

      {/* processing: rotating arc */}
      {state === 'processing' && (
        <span
          aria-hidden
          className="anim-spin-slow absolute size-40 rounded-full sm:size-44"
          style={{ background: 'conic-gradient(from 0deg, transparent 0 60%, var(--accent) 85%, var(--saffron) 100%)', mask: 'radial-gradient(farthest-side, transparent calc(100% - 5px), #000 calc(100% - 4px))', WebkitMask: 'radial-gradient(farthest-side, transparent calc(100% - 5px), #000 calc(100% - 4px))' }}
        />
      )}

      <motion.button
        type="button"
        onClick={onClick}
        disabled={disabled}
        aria-label={label}
        aria-pressed={state === 'listening'}
        animate={{ scale: state === 'processing' ? [1, 1.05, 1] : scale }}
        transition={state === 'processing' ? { duration: 1.4, repeat: Infinity, ease: 'easeInOut' } : { type: 'spring', stiffness: 260, damping: 20 }}
        whileTap={{ scale: 0.94 }}
        className={cn(
          'relative z-10 grid size-28 place-items-center rounded-full text-white shadow-[0_12px_40px_-8px_color-mix(in_srgb,var(--accent)_70%,transparent)] outline-offset-4 transition-[filter] duration-500 sm:size-32',
          'bg-brand disabled:cursor-not-allowed',
          state === 'muted' && 'grayscale',
        )}
      >
        <span aria-hidden className="absolute inset-0 rounded-full bg-gradient-to-b from-white/25 to-transparent" />
        <Icon className={cn('relative size-11 sm:size-12', state === 'processing' && 'animate-spin', state === 'listening' && Icon === Square && 'size-9 fill-current')} strokeWidth={state === 'listening' && Icon === Square ? 0 : 2} />
      </motion.button>
    </div>
  )
}
