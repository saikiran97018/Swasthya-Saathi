import { useEffect, useId, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { ChevronDown, Copy, CloudOff, HeartPulse, Info, LoaderCircle, MapPin, MessageSquareText, Navigation, Phone, Plus, Route, Share2, Siren, Trash2, TriangleAlert, UserRound, Video } from 'lucide-react'
import { useCreateEmergencyContact, useDeleteEmergencyContact, useEmergencyContacts, useSos } from '@/api/hooks'
import type { EmergencyContact, SosNumber } from '@/api/types'
import { Badge, Button } from '@/components/ui/primitives'
import { useToast } from '@/components/ui/Toast'
import {
  MAX_EMERGENCY_CONTACTS,
  FALLBACK_DISCLAIMER,
  GeoError,
  isValidContactPhone,
  locate,
  type Position,
  mapsLink,
  pickSos,
  readContactsCache,
  readSavedCity,
  readSosCache,
  saveCity,
  smsLink,
  sosMessage,
  telLink,
  withNationalNumbers,
  writeContactsCache,
  writeSosCache,
  type GeoFailure,
} from '@/lib/sos'
import { directionsLink, distanceLabel, placeAddress, placeKindLabel } from '@/lib/places'
import { istDate, istTime } from '@/lib/time'

const input = 'h-12 w-full rounded-2xl border border-line bg-bg/60 px-4 text-[15px] outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/25'

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms)
    return () => window.clearTimeout(t)
  }, [value, ms])
  return v
}

function Section({ id, icon, title, aside, children }: { id: string; icon: ReactNode; title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="card p-4 md:p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 id={id} className="flex items-center gap-2.5 text-lg font-bold">
          <span className="grid size-9 place-items-center rounded-xl bg-accent-soft text-accent-text">{icon}</span>
          {title}
        </h2>
        {aside}
      </div>
      {children}
    </section>
  )
}

export default function SosPage() {
  const [city, setCity] = useState(readSavedCity)
  const debouncedCity = useDebounced(city.trim(), 500)
  // Once the person has shared their location, the same coordinates also find the nearest care.
  const [pos, setPos] = useState<Position | null>(null)
  const sos = useSos(pos ? { city: '', lat: pos.lat, lon: pos.lon } : { city: debouncedCity })
  const cacheKey = pos ? `@${pos.lat.toFixed(3)},${pos.lon.toFixed(3)}` : debouncedCity
  const cache = useMemo(() => readSosCache(), [sos.dataUpdatedAt])

  // Remember the last successful answer so the page still works with no network.
  useEffect(() => {
    if (sos.data) writeSosCache(sos.data, cacheKey)
  }, [sos.data, cacheKey])
  useEffect(() => saveCity(city), [city])

  const { info, source } = pickSos(sos.data, cache, cacheKey)
  const offline = !sos.data && (sos.isError || sos.fetchStatus === 'paused')
  const numbers = withNationalNumbers(info.numbers)
  const helplines = numbers.filter((n) => n.code !== '112' && n.code !== '108')

  const contacts = useEmergencyContacts()
  const [cachedContacts] = useState(readContactsCache)
  useEffect(() => {
    if (contacts.data) writeContactsCache(contacts.data)
  }, [contacts.data])
  const contactList = contacts.data ?? (contacts.isError ? cachedContacts : [])

  const sharedLink = pos ? mapsLink(pos.lat, pos.lon) : null
  const hasOsm = info.nearby.some((n) => n.source === 'openstreetmap')

  return (
    <div className="mx-auto w-full max-w-3xl space-y-4 px-4 py-5 md:px-6 md:py-8">
      <header>
        <h1 className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[1.65rem] leading-tight font-bold tracking-tight text-danger md:text-3xl">
          <Siren className="size-7 shrink-0" aria-hidden /> Emergency help
        </h1>
        <p className="mt-1.5 text-muted">Tap a button to call. Your phone will ask you to confirm before it dials.</p>
        {offline && (
          <p className="mt-2" role="status">
            <Badge tone="warn" className="px-2.5 py-1 text-xs">
              <CloudOff className="size-3.5" aria-hidden />
              {source === 'cache' && cache ? `Offline copy from ${istDate(cache.savedAt)}, ${istTime(cache.savedAt)} IST` : 'Offline: built-in national numbers'}
            </Badge>
          </p>
        )}
      </header>

      {/* (a) the two calls */}
      <section aria-label="Call for help" className="grid gap-3 sm:grid-cols-2">
        <a href="tel:112" className="flex min-h-[7.5rem] flex-col items-center justify-center gap-1 rounded-[1.5rem] bg-danger px-4 py-5 text-center text-white shadow-[var(--shadow-pop)] transition active:scale-[0.98]">
          <span className="flex items-center gap-3 text-4xl font-extrabold tracking-tight"><Phone className="size-8" aria-hidden /> Call 112</span>
          <span className="text-sm font-medium text-white/90">National emergency number</span>
        </a>
        <a href="tel:108" className="flex min-h-[7.5rem] flex-col items-center justify-center gap-1 rounded-[1.5rem] border-[3px] border-danger bg-elev px-4 py-5 text-center text-danger shadow-[var(--shadow-card)] transition active:scale-[0.98]">
          <span className="flex items-center gap-3 text-4xl font-extrabold tracking-tight"><Phone className="size-8" aria-hidden /> Call 108</span>
          <span className="text-sm font-semibold">Ambulance</span>
        </a>
      </section>

      {/* (b) share location */}
      <ShareLocation contacts={contactList} onLocated={setPos} located={pos} />

      {/* (c) emergency contacts */}
      <Contacts
        contacts={contactList}
        loading={contacts.isLoading}
        error={contacts.isError ? (contacts.error instanceof Error ? contacts.error.message : 'Could not load your contacts.') : null}
        stale={contacts.isError && !contacts.data}
        onRetry={() => void contacts.refetch()}
        link={sharedLink}
      />

      {/* (d) nearest care */}
      <section aria-labelledby="near-h" className="card p-4 md:p-5">
        <h2 id="near-h" className="mb-3 flex items-center gap-2.5 text-lg font-bold">
          <span className="grid size-9 place-items-center rounded-xl bg-accent-soft text-accent-text"><HeartPulse className="size-5" aria-hidden /></span>
          Nearest care
        </h2>
        <label htmlFor="sos-city" className="label-caps mb-1.5 block">Your city or town</label>
        <input id="sos-city" value={city} onChange={(e) => { setCity(e.target.value); setPos(null) }} maxLength={80} placeholder="For example Guntur" autoComplete="address-level2" className={input} />
        {pos && (
          <p className="mt-2 text-sm text-muted">
            Showing places near your shared location.{' '}
            <button type="button" onClick={() => setPos(null)} className="font-semibold text-accent-text underline underline-offset-2">Use the city instead</button>
          </p>
        )}
        <div className="mt-3" aria-live="polite">
          {!debouncedCity && !pos ? (
            <p className="text-sm text-muted">Type your city, or tap Share my location above, to see hospitals and clinics near you.</p>
          ) : sos.isLoading && !cache ? (
            <p className="flex items-center gap-2 text-sm text-muted"><LoaderCircle className="size-4 animate-spin" aria-hidden /> Looking for care nearby…</p>
          ) : info.nearby.length === 0 ? (
            <p className="text-sm text-muted">{offline ? 'Nearby places need an internet connection. Call 112 or 108.' : 'No places found here right now. Call 108 for an ambulance, or try a bigger town nearby.'}</p>
          ) : (
            <>
              <ul className="divide-y divide-line">
                {info.nearby.map((n) => {
                  const dist = distanceLabel(n.distance_km)
                  const hasPoint = typeof n.lat === 'number' && typeof n.lon === 'number'
                  return (
                    <li key={n.code} className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3 first:pt-0 last:pb-0">
                      <div className="min-w-0 flex-1 basis-48">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="font-semibold break-words">{n.name}</span>
                          {n.is_demo && <Badge tone="saffron" title="Sample data, not a real place.">Sample data</Badge>}
                          {n.teleconsultation && <Badge tone="accent"><Video className="size-3" aria-hidden /> Video</Badge>}
                        </div>
                        <p className="mt-0.5 text-sm break-words text-muted">{[placeKindLabel(n.kind), dist, placeAddress(n)].filter(Boolean).join(' · ')}</p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        {n.phone && (
                          <a href={telLink(n.phone)} aria-label={`Call ${n.name}`} className="inline-flex h-11 items-center gap-1.5 rounded-2xl border border-line bg-elev px-4 text-sm font-semibold text-accent-text hover:bg-soft">
                            <Phone className="size-4" aria-hidden /> {n.phone}
                          </a>
                        )}
                        {hasPoint && (
                          <a href={directionsLink(n.lat as number, n.lon as number)} target="_blank" rel="noopener noreferrer" aria-label={`Get directions to ${n.name}`} className="inline-flex h-11 items-center gap-1.5 rounded-2xl border border-line bg-elev px-4 text-sm font-semibold hover:bg-soft">
                            <Route className="size-4" aria-hidden /> Directions
                          </a>
                        )}
                      </div>
                    </li>
                  )
                })}
              </ul>
              {hasOsm && <p className="mt-3 text-xs text-muted">Phone numbers and hours may be out of date: call before you go.</p>}
            </>
          )}
        </div>
      </section>

      {/* (e) first aid */}
      <Section id="aid-h" icon={<HeartPulse className="size-5" aria-hidden />} title="First aid until help arrives">
        {info.first_aid.length === 0 ? (
          <p className="text-sm text-muted">{offline ? 'First-aid steps need an internet connection the first time. Call 112 and follow what the operator tells you.' : sos.isLoading ? 'Loading…' : 'No first-aid guides are available right now. Call 112 and follow what the operator tells you.'}</p>
        ) : (
          <div className="divide-y divide-line rounded-2xl border border-line">
            {info.first_aid.map((g) => (
              <details key={g.id} className="group">
                <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 font-semibold marker:hidden [&::-webkit-details-marker]:hidden">
                  <span className="min-w-0 break-words">{g.title}</span>
                  <ChevronDown className="size-5 shrink-0 text-muted transition group-open:rotate-180" aria-hidden />
                </summary>
                <div className="space-y-3 px-4 pb-4">
                  <ol className="list-decimal space-y-1.5 pl-5 text-[15px] leading-relaxed marker:font-semibold marker:text-accent-text">
                    {g.steps.map((s, i) => <li key={i} className="break-words">{s}</li>)}
                  </ol>
                  {g.call_if && (
                    <p className="flex items-start gap-2 rounded-xl bg-danger-soft px-3 py-2.5 text-sm text-danger">
                      <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                      <span><strong>Call 112 if:</strong> {g.call_if}</span>
                    </p>
                  )}
                </div>
              </details>
            ))}
          </div>
        )}
      </Section>

      {/* (f) other helplines */}
      <Section id="help-h" icon={<Phone className="size-5" aria-hidden />} title="Other helplines">
        <ul className="divide-y divide-line">
          {helplines.map((n) => <HelplineRow key={n.code} n={n} />)}
        </ul>
      </Section>

      {/* (g) disclaimer */}
      <p className="flex items-start gap-2.5 rounded-2xl border border-line bg-elev/70 px-4 py-3 text-sm leading-relaxed" role="note">
        <Info className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
        <span><strong>Please note.</strong> {info.disclaimer || FALLBACK_DISCLAIMER} This page does not call or notify anyone by itself. If you are in danger, call 112.</span>
      </p>
    </div>
  )
}

function HelplineRow({ n }: { n: SosNumber }) {
  return (
    <li className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
      <div className="min-w-0 flex-1">
        <p className="font-semibold break-words">{n.label}</p>
        <p className="text-sm break-words text-muted">{n.description}</p>
      </div>
      <a href={telLink(n.code)} aria-label={`Call ${n.label}, ${n.code}`} className="inline-flex h-11 min-w-[5.5rem] shrink-0 items-center justify-center gap-1.5 rounded-2xl border border-line bg-elev px-3.5 font-bold text-accent-text hover:bg-soft">
        <Phone className="size-4" aria-hidden /> {n.code}
      </a>
    </li>
  )
}

// ---------------------------------------------------------------- (b) share my location

type Locating = { state: 'idle' } | { state: 'locating' } | { state: 'error'; kind: GeoFailure; message: string }

function ShareLocation({ contacts, located: pos, onLocated }: { contacts: EmergencyContact[]; located: Position | null; onLocated: (pos: Position) => void }) {
  const located = pos ? mapsLink(pos.lat, pos.lon) : null
  const toast = useToast()
  const [status, setStatus] = useState<Locating>({ state: 'idle' })
  const [accuracy, setAccuracy] = useState<number | null>(null)
  const [note, setNote] = useState('')
  const canShare = typeof navigator !== 'undefined' && typeof navigator.share === 'function'

  const find = async () => {
    setStatus({ state: 'locating' })
    setNote('')
    try {
      const found = await locate()
      setAccuracy(found.accuracy)
      onLocated(found)
      setStatus({ state: 'idle' })
    } catch (e) {
      const kind: GeoFailure = e instanceof GeoError ? e.kind : 'unavailable'
      setStatus({ state: 'error', kind, message: e instanceof Error ? e.message : 'Your location is not available right now.' })
    }
  }

  const message = located ? sosMessage(located) : ''

  const share = async () => {
    try {
      await navigator.share({ title: 'I need help', text: message })
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setNote('Sharing did not work. Use Copy instead.')
    }
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message)
      setNote('Copied. Paste it into a message.')
    } catch {
      // Older browsers: select the text so the person can copy it by hand.
      const el = document.getElementById('sos-link-text')
      if (el) {
        const range = document.createRange()
        range.selectNodeContents(el)
        const sel = window.getSelection()
        sel?.removeAllRanges()
        sel?.addRange(range)
      }
      setNote('Could not copy automatically. The text is selected: copy it by hand.')
      toast.info('Select the text and copy it.')
    }
  }

  return (
    <section aria-labelledby="loc-h" className="card p-4 md:p-5">
      <h2 id="loc-h" className="mb-1 flex items-center gap-2.5 text-lg font-bold">
        <span className="grid size-9 place-items-center rounded-xl bg-accent-soft text-accent-text"><MapPin className="size-5" aria-hidden /></span>
        Share my location
      </h2>
      <p className="mb-3 text-sm text-muted">Your phone asks for permission only when you tap the button. Nothing is sent until you tap Send in your messaging app.</p>

      <Button variant="primary" size="lg" className="w-full sm:w-auto" onClick={() => void find()} disabled={status.state === 'locating'}>
        {status.state === 'locating' ? <LoaderCircle className="size-5 animate-spin" aria-hidden /> : <Navigation className="size-5" aria-hidden />}
        {status.state === 'locating' ? 'Finding your location…' : located ? 'Update my location' : 'Share my location'}
      </Button>

      <div aria-live="polite" className="mt-3 space-y-3">
        {status.state === 'error' && (
          <p role="alert" className="flex items-start gap-2 rounded-xl border border-danger/30 bg-danger-soft px-3 py-2.5 text-sm text-danger">
            <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden /> <span>{status.message}</span>
          </p>
        )}
        {located && (
          <div className="space-y-3">
            <div className="rounded-2xl bg-soft/70 p-3.5">
              <p className="text-xs font-semibold text-muted">Your message</p>
              <p id="sos-link-text" className="mt-1 text-[15px] break-all">{message}</p>
              {accuracy !== null && <p className="mt-1 text-xs text-muted">Accurate to about {Math.max(1, Math.round(accuracy))} m</p>}
              <a href={located} target="_blank" rel="noopener noreferrer" className="mt-2 inline-flex min-h-10 items-center gap-1.5 text-sm font-semibold text-accent-text underline-offset-2 hover:underline">
                <MapPin className="size-4" aria-hidden /> Check it on the map
              </a>
            </div>

            {contacts.length > 0 ? (
              <ul className="space-y-2" aria-label="Text your location to a contact">
                {contacts.map((c) => (
                  <li key={c.id}>
                    <a href={smsLink(c.phone, message)} className="flex min-h-12 items-center gap-3 rounded-2xl border border-line bg-elev px-4 py-2 font-semibold transition hover:bg-soft active:scale-[0.99]">
                      <MessageSquareText className="size-5 shrink-0 text-accent-text" aria-hidden />
                      <span className="min-w-0 flex-1 break-words">Text {c.name}</span>
                      <span className="text-sm font-normal text-muted">{c.phone}</span>
                    </a>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted">Add an emergency contact below to text them your location in one tap.</p>
            )}

            <div className="flex flex-wrap gap-2">
              {canShare && (
                <Button variant="secondary" onClick={() => void share()}><Share2 className="size-4" aria-hidden /> Share…</Button>
              )}
              <Button variant="secondary" onClick={() => void copy()}><Copy className="size-4" aria-hidden /> Copy message</Button>
            </div>
            {note && <p className="text-sm text-muted" role="status">{note}</p>}
          </div>
        )}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------- (c) my emergency contacts

function Contacts({ contacts, loading, error, stale, onRetry, link }: { contacts: EmergencyContact[]; loading: boolean; error: string | null; stale: boolean; onRetry: () => void; link: string | null }) {
  const toast = useToast()
  const add = useCreateEmergencyContact()
  const remove = useDeleteEmergencyContact()
  const ids = { name: useId(), phone: useId(), relation: useId() }
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [relation, setRelation] = useState('')
  const [errors, setErrors] = useState<{ name?: string; phone?: string; form?: string }>({})
  const [removing, setRemoving] = useState<string | null>(null)
  const full = contacts.length >= MAX_EMERGENCY_CONTACTS

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const found: typeof errors = {}
    if (name.trim().length < 2) found.name = 'Enter a name.'
    if (!isValidContactPhone(phone)) found.phone = 'Enter a 10-digit mobile number, or a number with its country code (for example +91…).'
    setErrors(found)
    if (found.name || found.phone) return
    add.mutate(
      { name: name.trim(), phone: phone.trim(), ...(relation.trim() ? { relation: relation.trim() } : {}) },
      {
        onSuccess: () => {
          setName('')
          setPhone('')
          setRelation('')
          setOpen(false)
          toast.success('Emergency contact saved')
        },
        onError: (err) => setErrors({ form: err instanceof Error ? err.message : 'Could not save the contact.' }),
      },
    )
  }

  const confirmRemove = (c: EmergencyContact) =>
    remove.mutate(c.id, {
      onSuccess: () => {
        setRemoving(null)
        toast.success(`${c.name} removed`)
      },
      onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not remove the contact'),
    })

  return (
    <section aria-labelledby="ec-h" className="card p-4 md:p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 id="ec-h" className="flex items-center gap-2.5 text-lg font-bold">
          <span className="grid size-9 place-items-center rounded-xl bg-accent-soft text-accent-text"><UserRound className="size-5" aria-hidden /></span>
          My emergency contacts
        </h2>
        <span className="text-xs font-semibold text-muted tabular-nums">{contacts.length} of {MAX_EMERGENCY_CONTACTS}</span>
      </div>

      {error && (
        <div role="alert" className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-xl bg-warn-soft px-3 py-2.5 text-sm text-warn">
          <span className="min-w-0 flex-1">{stale ? 'Could not reach the server. Showing the contacts saved on this phone.' : error}</span>
          <Button size="sm" onClick={onRetry}>Retry</Button>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : contacts.length === 0 ? (
        <p className="text-sm text-muted">No contacts yet. Add up to {MAX_EMERGENCY_CONTACTS} people you trust, and you can call or text them from here.</p>
      ) : (
        <ul className="divide-y divide-line">
          {contacts.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3 first:pt-0 last:pb-0">
              <div className="min-w-0 flex-1 basis-40">
                <p className="font-semibold break-words">{c.name}{c.relation && <span className="ml-1.5 text-sm font-normal text-muted">· {c.relation}</span>}</p>
                <p className="text-sm text-muted tabular-nums">{c.phone}</p>
              </div>
              <div className="flex items-center gap-2">
                <a href={telLink(c.phone)} aria-label={`Call ${c.name}`} className="inline-flex h-11 items-center gap-1.5 rounded-2xl bg-accent px-4 text-sm font-semibold text-accent-fg hover:brightness-110">
                  <Phone className="size-4" aria-hidden /> Call
                </a>
                <a href={smsLink(c.phone, link ? sosMessage(link) : 'I need help.')} aria-label={`Text ${c.name}`} className="inline-flex h-11 items-center gap-1.5 rounded-2xl border border-line bg-elev px-4 text-sm font-semibold hover:bg-soft">
                  <MessageSquareText className="size-4" aria-hidden /> Text
                </a>
                {removing === c.id ? (
                  <Button size="sm" variant="danger" className="h-11" loading={remove.isPending} onClick={() => confirmRemove(c)} aria-label={`Confirm: remove ${c.name}`}>Remove?</Button>
                ) : (
                  <button type="button" onClick={() => setRemoving(c.id)} aria-label={`Remove ${c.name}`} className="grid size-11 place-items-center rounded-2xl text-muted transition hover:bg-danger-soft hover:text-danger">
                    <Trash2 className="size-[18px]" aria-hidden />
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {open ? (
        <form onSubmit={submit} noValidate className="mt-4 space-y-3 rounded-2xl bg-soft/60 p-3.5">
          <div>
            <label htmlFor={ids.name} className="label-caps mb-1.5 block">Name</label>
            <input id={ids.name} value={name} maxLength={80} autoComplete="off" onChange={(e) => setName(e.target.value)} aria-invalid={!!errors.name} aria-describedby={errors.name ? `${ids.name}-e` : undefined} className={input} />
            {errors.name && <p id={`${ids.name}-e`} role="alert" className="mt-1 text-sm font-medium text-danger">{errors.name}</p>}
          </div>
          <div>
            <label htmlFor={ids.phone} className="label-caps mb-1.5 block">Phone number</label>
            <input id={ids.phone} value={phone} inputMode="tel" autoComplete="off" maxLength={20} onChange={(e) => setPhone(e.target.value)} aria-invalid={!!errors.phone} aria-describedby={errors.phone ? `${ids.phone}-e` : undefined} className={input} />
            {errors.phone && <p id={`${ids.phone}-e`} role="alert" className="mt-1 text-sm font-medium text-danger">{errors.phone}</p>}
          </div>
          <div>
            <label htmlFor={ids.relation} className="label-caps mb-1.5 block">Relation <span className="font-normal normal-case">(optional)</span></label>
            <input id={ids.relation} value={relation} maxLength={40} placeholder="For example mother, neighbour" onChange={(e) => setRelation(e.target.value)} className={input} />
          </div>
          {errors.form && <p role="alert" className="rounded-xl border border-danger/30 bg-danger-soft px-3 py-2.5 text-sm text-danger">{errors.form}</p>}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="primary" loading={add.isPending}>Save contact</Button>
            <Button type="button" onClick={() => { setOpen(false); setErrors({}) }}>Cancel</Button>
          </div>
        </form>
      ) : (
        <div className="mt-4">
          <Button variant="soft" disabled={full} onClick={() => setOpen(true)}><Plus className="size-4" aria-hidden /> Add a contact</Button>
          {full && <p className="mt-2 text-sm text-muted">You can save up to {MAX_EMERGENCY_CONTACTS} contacts. Remove one to add another.</p>}
        </div>
      )}
    </section>
  )
}
