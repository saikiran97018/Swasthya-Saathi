import { useState } from 'react'
import { motion } from 'framer-motion'
import {
  CalendarCheck,
  CalendarClock,
  CalendarX,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleSlash,
  CloudSun,
  Languages,
  ListChecks,
  LoaderCircle,
  Phone,
  Search,
  ShieldCheck,
  Siren,
  Star,
  Stethoscope,
  Wrench,
  type LucideIcon,
} from 'lucide-react'
import type { ToolExecution } from '@/api/types'
import { cn, durationMs, humanize } from '@/lib/format'
import { Button } from '@/components/ui/primitives'
import { richResult } from './ToolResults'

/** Decorative icon chosen from keywords in the tool name; unknown tools get a wrench. */
export function toolIcon(name: string): LucideIcon {
  const n = name.toLowerCase()
  if (n.includes('urgen') || n.includes('emergency') || n.includes('triage')) return Siren
  if (n.includes('provider') || n.includes('doctor')) return Stethoscope
  if (n.includes('cancel')) return CalendarX
  if (n.includes('reschedule')) return CalendarClock
  if (n.includes('appointment') || n.includes('availability') || n.includes('slot') || n.includes('follow') || n.includes('book')) return CalendarCheck
  if (n.includes('feedback') || n.includes('rating')) return Star
  if (n.includes('weather')) return CloudSun
  if (n.includes('task')) return ListChecks
  if (n.includes('language')) return Languages
  if (n.includes('directory') || n.includes('phone') || n.includes('helpline')) return Phone
  if (n.includes('search') || n.includes('knowledge') || n.includes('lookup')) return Search
  return Wrench
}

const STATUS: Record<ToolExecution['status'], { label: string; tone: string; icon: LucideIcon }> = {
  running: { label: 'Working…', tone: 'text-accent-text', icon: LoaderCircle },
  success: { label: 'Done', tone: 'text-ok', icon: CircleCheck },
  error: { label: 'Failed', tone: 'text-danger', icon: CircleAlert },
  awaiting_confirmation: { label: 'Needs your OK', tone: 'text-warn', icon: ShieldCheck },
  denied: { label: 'Declined', tone: 'text-muted', icon: CircleSlash },
  cancelled: { label: 'Cancelled', tone: 'text-muted', icon: CircleSlash },
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (Array.isArray(v)) return v.map(formatValue).join(', ')
  if (typeof v === 'object') return Object.entries(v as Record<string, unknown>).map(([k, x]) => `${humanize(k)}: ${formatValue(x)}`).join(' · ')
  return String(v)
}

export function ArgumentList({ args }: { args: Record<string, unknown> }) {
  const entries = Object.entries(args)
  if (!entries.length) return null
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{humanize(k)}</dt>
          <dd className="min-w-0 font-medium break-words">{formatValue(v)}</dd>
        </div>
      ))}
    </dl>
  )
}

/** One tool call: status, a one-line summary, and (optionally) expandable arguments + raw result. */
export function ToolCard({ tool, showDetails, compact, rich = true }: { tool: ToolExecution; showDetails: boolean; compact?: boolean; rich?: boolean }) {
  const [open, setOpen] = useState(false)
  const s = STATUS[tool.status] ?? STATUS.running
  const StatusIcon = s.icon
  const Icon = toolIcon(tool.tool_name)
  const canExpand = showDetails && (Object.keys(tool.arguments).length > 0 || tool.result)
  const body = rich ? richResult(tool) : null

  return (
    <motion.div layout initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="overflow-hidden rounded-xl border border-line bg-soft/60">
      <button
        type="button"
        disabled={!canExpand}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={canExpand ? open : undefined}
        className={cn('flex w-full items-center gap-2.5 px-3 text-left', compact ? 'py-1.5' : 'py-2.5', canExpand && 'hover:bg-soft')}
      >
        <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-elev text-accent-text shadow-sm">
          <Icon className="size-4" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2 text-sm font-medium">
            <span className="truncate">{humanize(tool.tool_name)}</span>
            {tool.duration_ms !== null && <span className="shrink-0 text-xs font-normal text-muted">{durationMs(tool.duration_ms)}</span>}
          </span>
          {(tool.summary || tool.error) && <span className={cn('block truncate text-xs', tool.status === 'error' ? 'text-danger' : 'text-muted')}>{tool.error ?? tool.summary}</span>}
        </span>
        <span className={cn('flex shrink-0 items-center gap-1 text-xs font-medium', s.tone)}>
          <StatusIcon className={cn('size-4', tool.status === 'running' && 'animate-spin')} aria-hidden />
          <span className="hidden sm:inline">{s.label}</span>
        </span>
        {canExpand && <ChevronRight className={cn('size-4 shrink-0 text-muted transition', open && 'rotate-90')} aria-hidden />}
      </button>

      {body && <div className="border-t border-line bg-elev/40 px-3 py-3">{body}</div>}

      {open && canExpand && (
        <div className="space-y-3 border-t border-line bg-elev/60 px-3 py-3 text-xs">
          {Object.keys(tool.arguments).length > 0 && (
            <div>
              <div className="mb-1 font-medium text-muted uppercase tracking-wide">Details sent</div>
              <ArgumentList args={tool.arguments} />
            </div>
          )}
          {tool.result && (
            <div>
              <div className="mb-1 font-medium text-muted uppercase tracking-wide">Result</div>
              <pre className="scroll-thin max-h-56 overflow-auto rounded-lg bg-soft p-2.5 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap break-words">{JSON.stringify(tool.result, null, 2)}</pre>
            </div>
          )}
        </div>
      )}
    </motion.div>
  )
}

/** Prominent card for a sensitive tool call waiting for the user's yes/no. */
export function ConfirmationCard({ tool, busy, onConfirm }: { tool: ToolExecution; busy: boolean; onConfirm: (approve: boolean) => void }) {
  const Icon = toolIcon(tool.tool_name)
  return (
    <motion.div
      initial={{ opacity: 0, y: 8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      role="group"
      aria-label="Confirmation needed"
      className="overflow-hidden rounded-2xl border-2 border-saffron/60 bg-saffron-soft/50 shadow-[var(--shadow-card)]"
    >
      <div className="flex items-center gap-2.5 border-b border-saffron/30 px-4 py-2.5">
        <span className="grid size-8 place-items-center rounded-lg bg-saffron text-black">
          <ShieldCheck className="size-[18px]" aria-hidden />
        </span>
        <div className="min-w-0">
          <div className="text-sm font-semibold">Please confirm</div>
          <div className="flex items-center gap-1.5 text-xs text-muted">
            <Icon className="size-3.5" aria-hidden />
            {humanize(tool.tool_name)}
          </div>
        </div>
      </div>
      <div className="space-y-3 px-4 py-3">
        {tool.explanation && <p className="text-base leading-snug font-semibold break-words">{tool.explanation}</p>}
        {Object.keys(tool.arguments).length > 0 && (
          <details className="group rounded-xl bg-elev/70 p-3" open={!tool.explanation}>
            <summary className="cursor-pointer text-xs font-medium tracking-wide text-muted uppercase select-none">Details</summary>
            <div className="mt-2">
              <ArgumentList args={tool.arguments} />
            </div>
          </details>
        )}
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="secondary" disabled={busy} onClick={() => onConfirm(false)}>
            Cancel
          </Button>
          <Button variant="primary" loading={busy} onClick={() => onConfirm(true)}>
            Confirm
          </Button>
        </div>
      </div>
    </motion.div>
  )
}
