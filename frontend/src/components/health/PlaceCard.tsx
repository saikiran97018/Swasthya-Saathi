import { Building2, CalendarCheck, Clock, Globe, Hospital, MapPin, Phone, Route, Stethoscope, Siren } from 'lucide-react'
import type { Place, PlaceKind } from '@/api/types'
import { Badge, Button } from '@/components/ui/primitives'
import { humanize } from '@/lib/format'
import { directionsLink, distanceLabel, placeAddress, placeKindLabel, safeWebsite, telLinkFor, visitModeFor, websiteHost } from '@/lib/places'

export const specialtyLabel = (s: string) => (s === 'ent' ? 'ENT' : humanize(s))

const KIND_ICON: Record<PlaceKind, typeof Hospital> = { hospital: Hospital, clinic: Building2, doctor: Stethoscope, phc: Building2, other: Building2 }

/**
 * A real place near the person. Map places carry no fee, rating or availability, so none is shown:
 * only what the data says (name, kind, address, phone, hours, website) and how far away it is.
 */
export function PlaceCard({ place: p, onSelect }: { place: Place; onSelect: () => void }) {
  const Icon = KIND_ICON[p.kind] ?? Building2
  const dist = distanceLabel(p.distance_km)
  const address = placeAddress(p)
  const phone = telLinkFor(p.phone)
  const site = safeWebsite(p.website)
  const book = visitModeFor(p) === 'book'
  const hasPoint = Number.isFinite(p.lat) && Number.isFinite(p.lon)

  return (
    <article className="card flex h-full flex-col p-4" aria-label={p.name}>
      <div className="flex items-start gap-3">
        <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-accent-soft text-accent-text"><Icon className="size-6" aria-hidden /></span>
        <div className="min-w-0 flex-1">
          <h3 className="leading-snug font-bold break-words">{p.name}</h3>
          <p className="text-sm text-muted">{[placeKindLabel(p.kind), dist].filter(Boolean).join(' · ')}</p>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {p.emergency && <Badge tone="danger"><Siren className="size-3" aria-hidden /> Emergency services</Badge>}
        {book && <Badge tone="ok"><CalendarCheck className="size-3" aria-hidden /> Online booking</Badge>}
        {p.specialties.slice(0, 4).map((s) => <Badge key={s} tone="accent">{specialtyLabel(s)}</Badge>)}
      </div>

      <div className="mt-3 space-y-1.5 text-sm">
        {address && <p className="flex items-start gap-1.5 break-words text-muted"><MapPin className="mt-0.5 size-4 shrink-0" aria-hidden />{address}</p>}
        {p.opening_hours && <p className="flex items-start gap-1.5 break-words text-muted"><Clock className="mt-0.5 size-4 shrink-0" aria-hidden /><span><span className="sr-only">Opening hours: </span>{p.opening_hours}</span></p>}
        {phone && p.phone && (
          <a href={phone} className="inline-flex min-h-8 items-center gap-1.5 font-medium text-accent-text hover:underline"><Phone className="size-4" aria-hidden />{p.phone}</a>
        )}
        {site && (
          <a href={site} target="_blank" rel="noopener noreferrer" className="flex min-h-8 items-center gap-1.5 font-medium break-all text-accent-text hover:underline"><Globe className="size-4 shrink-0" aria-hidden />{websiteHost(site)}</a>
        )}
      </div>

      <div className="mt-auto flex flex-wrap items-center gap-2 pt-4">
        {hasPoint && (
          <a
            href={directionsLink(p.lat, p.lon)}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`Get directions to ${p.name}`}
            className="inline-flex h-11 items-center gap-1.5 rounded-2xl border border-line bg-elev px-3.5 text-sm font-semibold hover:bg-soft"
          >
            <Route className="size-4" aria-hidden /> Get directions
          </a>
        )}
        <Button size="sm" variant="primary" className="h-11 flex-1 sm:flex-none" onClick={onSelect} aria-label={`${book ? 'Book an appointment at' : 'Plan a visit to'} ${p.name}`}>
          {book ? 'Book appointment' : 'Plan a visit'}
        </Button>
      </div>
    </article>
  )
}
