import { Link, useLocation } from 'react-router-dom'
import { Siren } from 'lucide-react'
import { cn } from '@/lib/format'

/**
 * Logo mark: a lotus (teal and green petals) with a small person figure in the centre petal.
 * Plain solid fills on purpose: a gradient referenced by id breaks when a copy of the logo sits in a display:none sidebar.
 */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={cn('size-9 shrink-0', className)} aria-hidden>
      {/* outer petals */}
      <path d="M32 50C19 52 7 47 3 38c11-2 24 2 29 12z" fill="#2a9d8f" />
      <path d="M32 50c13 2 25-3 29-12-11-2-24 2-29 12z" fill="#2a9d8f" />
      {/* middle petals */}
      <path d="M32 50C21 50 12 43 9 31c11 0 20 6 23 19z" fill="#4cbc8a" />
      <path d="M32 50c11 0 20-7 23-19-11 0-20 6-23 19z" fill="#4cbc8a" />
      {/* centre petal */}
      <path d="M32 9c-8 11-9 28 0 41 9-13 8-30 0-41z" fill="#0f6b64" />
      {/* person */}
      <circle cx="32" cy="22" r="3.6" fill="#fff" />
      <path d="M25.5 40c0-8.5 13-8.5 13 0z" fill="#fff" />
      <path d="M26 33.5l-3.5-3.2M38 33.5l3.5-3.2" stroke="#fff" strokeWidth="2" strokeLinecap="round" fill="none" />
    </svg>
  )
}

/** Wordmark: "Swasthya Saathi" in a bold teal, with the tagline underneath. */
export function Brand({ compact }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <LogoMark className="size-11" />
      {!compact && (
        <div className="min-w-0 leading-tight">
          <div className="text-[19px] leading-[1.05] font-extrabold tracking-tight text-accent-text">Swasthya<br />Saathi</div>
          <div className="mt-1 text-[10.5px] leading-snug text-muted">Your Health Guide,<br />in Your Language</div>
        </div>
      )}
    </div>
  )
}

/**
 * The one emergency control: a red SOS button in the header of every screen. It opens the full /sos page
 * (call 112 / 108, share location, contacts, first aid). There is deliberately no other emergency button in the shell.
 */
export function SosButton({ className }: { className?: string }) {
  const { pathname } = useLocation()
  return (
    <Link
      to="/sos"
      aria-label="SOS: emergency help"
      aria-current={pathname === '/sos' ? 'page' : undefined}
      className={cn(
        'inline-flex h-11 shrink-0 items-center gap-1.5 rounded-full bg-danger px-3.5 text-sm font-extrabold tracking-wide sm:px-4 text-white shadow-sm transition hover:brightness-110 active:scale-95 focus-visible:outline-offset-2',
        className,
      )}
    >
      <Siren className="size-[18px]" aria-hidden /> SOS
    </Link>
  )
}
