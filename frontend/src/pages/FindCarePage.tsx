import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { LoaderCircle, MapPinned, Navigation, SearchX, TriangleAlert } from 'lucide-react'
import { ApiError } from '@/api/client'
import { usePlaces } from '@/api/hooks'
import { SPECIALTIES } from '@/api/types'
import { useBooking } from '@/components/health/BookingSheet'
import { PlaceCard, specialtyLabel } from '@/components/health/PlaceCard'
import { Button, EmptyState, Skeleton, ToggleChip } from '@/components/ui/primitives'
import { placeQueryFrom, readCareCity, saveCareCity, type PlaceFilters } from '@/lib/places'
import { GeoError, locate } from '@/lib/sos'

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms)
    return () => window.clearTimeout(t)
  }, [value, ms])
  return v
}

const inputClass = 'h-12 w-full rounded-2xl border border-line bg-elev px-3.5 text-[15px] outline-none focus:border-accent focus:ring-2 focus:ring-accent/25'

const KINDS: { value: PlaceFilters['kind']; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'hospital', label: 'Hospitals' },
  { value: 'clinic', label: 'Clinics' },
  { value: 'doctor', label: 'Doctors' },
]

/** A friendly sentence for each way the place search can fail. */
function searchErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'place_not_found') return 'We could not find that town or city. Check the spelling, or try a bigger town nearby.'
    if (error.code === 'location_required') return 'Type your city or tap "Use my location" to search.'
    if (error.code === 'places_unavailable') return 'The map service is busy right now. Please try again in a moment.'
    if (error.code === 'network_error') return error.message
    return error.message
  }
  return 'Could not search for places. Please try again.'
}

export default function FindCarePage() {
  const { openBooking } = useBooking()
  const [params] = useSearchParams()
  const cityParam = params.get('city')?.trim().slice(0, 80) || null // set when the assistant opens this page for a city ("doctors in Guntur")
  const [city, setCity] = useState(() => cityParam ?? readCareCity())
  const [coords, setCoords] = useState<{ lat: number; lon: number } | null>(null)
  useEffect(() => {
    if (cityParam) {
      setCity(cityParam)
      setCoords(null)
    }
  }, [cityParam])
  const [kind, setKind] = useState<PlaceFilters['kind']>('')
  const [q, setQ] = useState('')
  const [specialty, setSpecialty] = useState('')
  const [geo, setGeo] = useState<{ state: 'idle' | 'locating' } | { state: 'error'; message: string }>({ state: 'idle' })

  const debounced = useDebounced({ city, q }, 450)
  useEffect(() => saveCareCity(city), [city])

  const query = useMemo(() => placeQueryFrom({ city: debounced.city, coords, kind, q: debounced.q, specialty }), [debounced, coords, kind, specialty])
  const { data, isLoading, isError, error, refetch, isFetching } = usePlaces(query)

  const useMyLocation = async () => {
    setGeo({ state: 'locating' })
    try {
      const pos = await locate()
      setCoords({ lat: pos.lat, lon: pos.lon })
      setGeo({ state: 'idle' })
    } catch (e) {
      setGeo({ state: 'error', message: e instanceof GeoError ? e.message : 'Your location is not available right now. Type your city instead.' })
    }
  }

  const items = data?.items ?? []
  const clear = () => {
    setKind('')
    setQ('')
    setSpecialty('')
  }

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-5 md:px-8 md:py-8">
      <header className="mb-5">
        <h1 className="text-[1.65rem] leading-tight font-bold tracking-tight md:text-3xl">Find a doctor</h1>
        <p className="mt-1.5 text-muted">Real hospitals, clinics and doctors near you, from OpenStreetMap. Call, get directions, or plan a visit.</p>
      </header>

      <section aria-label="Search" className="card mb-4 space-y-3 p-4">
        <div>
          <label htmlFor="f-city" className="label-caps mb-1.5 block">City or town</label>
          <div className="flex flex-wrap gap-2 sm:flex-nowrap">
            <input
              id="f-city"
              value={city}
              onChange={(e) => { setCity(e.target.value); setCoords(null) }}
              placeholder="For example Guntur"
              maxLength={80}
              autoComplete="address-level2"
              className={inputClass}
            />
            <Button variant="soft" className="w-full shrink-0 sm:w-auto" onClick={() => void useMyLocation()} disabled={geo.state === 'locating'}>
              {geo.state === 'locating' ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : <Navigation className="size-4" aria-hidden />}
              {geo.state === 'locating' ? 'Finding you…' : 'Use my location'}
            </Button>
          </div>
          {geo.state === 'error' && (
            <p role="alert" className="mt-2 flex items-start gap-2 text-sm text-danger"><TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />{geo.message}</p>
          )}
          {coords && (
            <p className="mt-2 text-sm text-muted">
              Showing places near your location.{' '}
              <button type="button" onClick={() => setCoords(null)} className="inline-flex min-h-8 items-center font-semibold text-accent-text underline underline-offset-2">Use the city instead</button>
            </p>
          )}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="f-q" className="label-caps mb-1.5 block">Name or speciality</label>
            <input id="f-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="For example skin, eye, child" maxLength={80} className={inputClass} />
          </div>
          <div>
            <label htmlFor="f-spec" className="label-caps mb-1.5 block">Kind of doctor</label>
            <select id="f-spec" value={specialty} onChange={(e) => setSpecialty(e.target.value)} className={inputClass}>
              <option value="">Any</option>
              {SPECIALTIES.map((s) => <option key={s} value={s}>{specialtyLabel(s)}</option>)}
            </select>
          </div>
        </div>

        <div role="group" aria-label="Kind of place" className="flex flex-wrap gap-2">
          {KINDS.map((k) => <ToggleChip key={k.value || 'all'} active={kind === k.value} onClick={() => setKind(k.value)}>{k.label}</ToggleChip>)}
        </div>
      </section>

      <div className="mb-3 px-1 text-sm text-muted" aria-live="polite">
        {!query ? null : isLoading ? 'Searching…' : isError ? '' : (
          <>
            {items.length} {items.length === 1 ? 'place' : 'places'} found{data?.center?.label ? ` near ${data.center.label}` : ''}{isFetching ? ' · updating…' : ''}
          </>
        )}
      </div>

      {!query ? (
        <div className="card">
          <EmptyState icon={<MapPinned className="size-6" />} title="Where do you want to look?">
            Type your city or town above, or tap Use my location. We will list hospitals, clinics and doctors nearby.
          </EmptyState>
        </div>
      ) : isLoading ? (
        <div className="space-y-3" aria-busy>{[0, 1, 2].map((i) => <Skeleton key={i} className="h-44" />)}</div>
      ) : isError ? (
        <div role="alert" className="card flex flex-wrap items-center justify-between gap-3 p-4">
          <span className="min-w-0 flex-1 text-sm text-danger">{searchErrorMessage(error)}</span>
          {!(error instanceof ApiError && (error.code === 'place_not_found' || error.code === 'location_required')) && <Button size="sm" onClick={() => void refetch()}>Try again</Button>}
        </div>
      ) : items.length === 0 ? (
        <div className="card">
          <EmptyState icon={<SearchX className="size-6" />} title="No places found" action={(kind || q || specialty) ? <Button onClick={clear}>Clear filters</Button> : undefined}>
            {data?.note ?? 'Try a bigger town nearby, or remove a filter.'}
          </EmptyState>
        </div>
      ) : (
        <>
          {data?.note && <p className="mb-3 rounded-2xl border border-line bg-elev/70 px-4 py-2.5 text-sm text-muted">{data.note}</p>}
          <ul className="grid gap-3.5 md:grid-cols-2">
            {items.map((p) => (
              <li key={p.id}><PlaceCard place={p} onSelect={() => openBooking(p)} /></li>
            ))}
          </ul>
        </>
      )}

      {query && !isLoading && !isError && (
        <p className="mt-4 px-1 text-xs leading-relaxed text-muted">
          {data?.attribution || 'Map data © OpenStreetMap contributors'}. Phone numbers and opening hours are added by volunteers and may be out of date: call before you go.
        </p>
      )}
    </div>
  )
}
