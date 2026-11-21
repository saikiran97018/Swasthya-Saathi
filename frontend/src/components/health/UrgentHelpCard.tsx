import { cn } from '@/lib/format'

/** A small drawn siren (red beacon with rays) for the urgent-help card. */
function SirenArt() {
  return (
    <svg viewBox="0 0 48 48" className="size-12 shrink-0" aria-hidden focusable="false">
      <path d="M24 3v5M9 9l3.5 3.5M39 9l-3.5 3.5M3 22h5M40 22h5" stroke="#e0554f" strokeWidth="2.6" strokeLinecap="round" fill="none" />
      <path d="M12 36c0-9 5-16 12-16s12 7 12 16z" fill="#d93a35" />
      <path d="M17 33c0-5 2.6-9 6-10" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" fill="none" opacity=".7" />
      <rect x="8" y="36" width="32" height="7" rx="3" fill="#7d8da1" />
      <rect x="11" y="38" width="26" height="3" rx="1.5" fill="#a9b6c6" />
    </svg>
  )
}

/** "Need urgent help?" card: a reminder only. The one emergency control is the red SOS button in the header, which opens the SOS page (calls to 112 and 108, location sharing, first aid). */
export function UrgentHelpCard({ className }: { className?: string }) {
  return (
    <section aria-labelledby="urgent-h" className={cn('rounded-[1.25rem] border border-danger/25 bg-danger-soft p-4', className)}>
      <div className="flex items-start gap-3">
        <SirenArt />
        <div className="min-w-0">
          <h2 id="urgent-h" className="text-lg font-bold text-danger">Need urgent help?</h2>
          <p className="mt-1 text-sm leading-snug text-fg/85">If you have chest pain, trouble breathing, heavy bleeding or feel faint, get help right away: tap the red SOS button at the top.</p>
        </div>
      </div>
    </section>
  )
}
