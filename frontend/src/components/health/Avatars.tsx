import { memo, useMemo, useState } from 'react'
import { Building2, Hospital, Stethoscope } from 'lucide-react'
import { avatarDataUri, initials } from '@/lib/avatar'
import { cn } from '@/lib/format'

/**
 * Illustrated avatar for a (demo) provider, generated locally from its code so it is the same everywhere.
 * Falls back to initials if the image cannot be shown. Decorative: the name is always written next to it.
 */
export const DoctorAvatar = memo(function DoctorAvatar({ seed, name, size = 48, className }: { seed: string; name?: string | null; size?: number; className?: string }) {
  const [failed, setFailed] = useState(false)
  const src = useMemo(() => avatarDataUri(seed), [seed])
  const style = { width: size, height: size }
  if (failed) return <InitialsBadge name={name ?? seed} size={size} className={className} />
  return <img src={src} alt="" aria-hidden width={size} height={size} style={style} onError={() => setFailed(true)} className={cn('shrink-0 rounded-full bg-accent-soft object-cover ring-2 ring-elev', className)} />
})

/** The signed-in person: a round badge with their initials. */
export function InitialsBadge({ name, size = 36, className }: { name: string | null | undefined; size?: number; className?: string }) {
  return (
    <span
      aria-hidden
      style={{ width: size, height: size, fontSize: Math.max(11, Math.round(size * 0.38)) }}
      className={cn('grid shrink-0 place-items-center rounded-full bg-accent-soft font-semibold text-accent-text ring-2 ring-elev', className)}
    >
      {initials(name)}
    </span>
  )
}

/**
 * A provider or place picture. Real places (from the map) get a plain building / hospital icon, never a person's face;
 * only partner and sample clinics use the drawn avatar.
 */
export function ProviderAvatar({ provider, size = 48, className }: { provider: { code: string; name: string; doctor_name: string | null; kind: string; source?: string | null }; size?: number; className?: string }) {
  if (provider.source !== 'openstreetmap') return <DoctorAvatar seed={provider.code} name={provider.doctor_name ?? provider.name} size={size} className={className} />
  const Icon = provider.kind === 'doctor' ? Stethoscope : provider.kind === 'hospital' ? Hospital : Building2
  return (
    <span aria-hidden style={{ width: size, height: size }} className={cn('grid shrink-0 place-items-center rounded-2xl bg-accent-soft text-accent-text', className)}>
      <Icon style={{ width: size * 0.5, height: size * 0.5 }} />
    </span>
  )
}
