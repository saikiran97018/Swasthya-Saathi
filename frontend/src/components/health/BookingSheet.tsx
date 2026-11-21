import { createContext, useCallback, useContext, useEffect, useId, useMemo, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Building2, CalendarCheck, CheckCircle2, Hospital, MapPin, Phone, Route, ShieldAlert, Stethoscope, UserPlus, Video, X } from 'lucide-react'
import { ApiError } from '@/api/client'
import { useCreateAppointment, useFamily, useMe, useProviderAvailability } from '@/api/hooks'
import type { Appointment, Place } from '@/api/types'
import { ConfirmationBadge, CopyChip } from '@/components/health/shared'
import { Button, Dialog, IconButton, SectionLabel, Skeleton } from '@/components/ui/primitives'
import { useLanguage } from '@/hooks/LanguageProvider'
import { bookingPayload, describeBookingError, validateBooking, type BookingField, type BookingForm } from '@/lib/booking'
import { bookingFieldsFor, relationLabel } from '@/lib/family'
import { cn, humanize } from '@/lib/format'
import { languageToSend } from '@/lib/language'
import { directionsLink, placeAddress, placeKindLabel, planDateBounds, telLinkFor, visitModeFor } from '@/lib/places'
import { dayOptions, groupSlotsByPeriod } from '@/lib/slots'
import { formatIST, formatSlotDate, formatSlotTime } from '@/lib/time'

interface BookingCtx {
  /** Open the sheet for a place. Partner clinics with online slots are booked; any other place is a planned visit. */
  openBooking: (place: Place) => void
}
const Ctx = createContext<BookingCtx | null>(null)

/** Mount once (inside the router): any screen can open the booking sheet for a place. */
export function BookingProvider({ children }: { children: ReactNode }) {
  const [place, setPlace] = useState<Place | null>(null)
  const openBooking = useCallback((p: Place) => setPlace(p), [])
  const close = useCallback(() => setPlace(null), [])
  // Browser back/forward should not leave a sheet floating over another screen.
  const { pathname } = useLocation()
  useEffect(() => setPlace(null), [pathname])
  const value = useMemo(() => ({ openBooking }), [openBooking])
  return (
    <Ctx.Provider value={value}>
      {children}
      <AnimatePresence>{place && <BookingSheet key={place.id} place={place} onClose={close} />}</AnimatePresence>
    </Ctx.Provider>
  )
}

export function useBooking(): BookingCtx {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useBooking must be used inside <BookingProvider>')
  return ctx
}

const field = 'w-full rounded-2xl border border-line bg-bg/60 px-4 text-[15px] outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/25'

const specialtyLabel = (s: string) => (s === 'ent' ? 'ENT' : humanize(s))

const NOT_CONFIRMED = 'This clinic has not confirmed this time. Call them to confirm.'

function whereLabel(p: Pick<Place, 'name' | 'address' | 'city'>, mode: string): string {
  if (mode === 'teleconsultation') return 'Video visit (online)'
  // Names often already include the city and some addresses are just the city: don't print it twice.
  const parts: string[] = []
  for (const x of [p.name, p.address, p.city]) if (x && !parts.some((y) => y.toLowerCase().includes(x.toLowerCase()))) parts.push(x)
  return parts.join(', ')
}

type Stage = 'form' | 'done'

function BookingSheet({ place: p, onClose }: { place: Place; onClose: () => void }) {
  const navigate = useNavigate()
  const { data: me } = useMe()
  const { selected } = useLanguage()
  const book = useCreateAppointment()
  const plan = visitModeFor(p) === 'plan'
  const avail = useProviderAvailability(plan ? null : p.provider_code)
  const family = useFamily()
  const ids = { reason: useId(), name: useId(), mobile: useId(), date: useId(), time: useId() }

  const [stage, setStage] = useState<Stage>('form')
  const [mode, setMode] = useState<BookingForm['mode']>('in_person')
  const [day, setDay] = useState<string | null>(null)
  const [time, setTime] = useState<string | null>(null)
  const [planDate, setPlanDate] = useState('')
  const [planTime, setPlanTime] = useState('')
  const [reason, setReason] = useState('')
  const [name, setName] = useState('')
  const [mobile, setMobile] = useState('')
  const [errors, setErrors] = useState<Partial<Record<BookingField, string>>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [booked, setBooked] = useState<Appointment | null>(null)
  // 'me' or a family member id
  const [forId, setForId] = useState<string>('me')
  const member = forId === 'me' ? null : (family.data?.find((m) => m.id === forId) ?? null)
  const bounds = useMemo(() => planDateBounds(), [])

  // Prefill the patient's name from the profile (never for a guest, whose name is a placeholder).
  useEffect(() => {
    if (me && !me.is_guest) setName((cur) => cur || me.display_name)
  }, [me])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !confirming && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose, confirming])

  const open = avail.data?.open_slots
  const days = useMemo(() => dayOptions(open ?? {}), [open])
  const activeDay = day && days.some((d) => d.key === day) ? day : (days[0]?.key ?? null)
  const groups = useMemo(() => groupSlotsByPeriod(activeDay ? (open?.[activeDay] ?? []) : []), [open, activeDay])
  const slot = plan
    ? planDate && planTime
      ? { date: planDate, time: planTime }
      : null
    : activeDay && time && (open?.[activeDay] ?? []).includes(time)
      ? { date: activeDay, time }
      : null
  const teleOk = avail.data?.provider.teleconsultation === true
  const fee = avail.data?.provider.fee_inr

  const form: BookingForm = {
    ...(plan ? { placeId: p.id } : { providerCode: p.provider_code ?? undefined }),
    slot,
    mode: plan ? 'in_person' : mode,
    name,
    mobile,
    reason,
    familyMemberId: member?.id ?? null,
  }
  const summary = slot ? `${!plan && mode === 'teleconsultation' ? 'Video visit' : 'In-person visit'} · ${formatSlotDate(slot.date)}, ${formatSlotTime(slot.time)} IST` : null
  const phoneHref = telLinkFor(p.phone)

  const chooseWho = (id: string) => {
    setForId(id)
    const m = id === 'me' ? null : (family.data?.find((x) => x.id === id) ?? null)
    const mine = me && !me.is_guest ? me.display_name : ''
    const fill = bookingFieldsFor(m, mine)
    setName(fill.name)
    setMobile(fill.mobile)
    setErrors((c) => ({ ...c, name: undefined, mobile: undefined }))
  }

  const review = () => {
    const found = validateBooking(form)
    setErrors(found)
    setFormError(null)
    if (Object.keys(found).length === 0) setConfirming(true)
  }

  const submit = () => {
    setFormError(null)
    book.mutate(bookingPayload(form, member?.language ?? languageToSend(selected)), {
      onSuccess: (appt) => {
        setBooked(appt)
        setConfirming(false)
        setStage('done')
      },
      onError: (err) => {
        const code = err instanceof ApiError ? err.code : ''
        const effect = describeBookingError(code, err instanceof Error ? err.message : '')
        setConfirming(false)
        if (effect.refreshSlots) {
          setTime(null)
          void avail.refetch()
        }
        if (effect.resetMode) setMode('in_person')
        if (effect.field) setErrors((cur) => ({ ...cur, [effect.field as BookingField]: effect.message }))
        else setFormError(effect.message)
        if (effect.field === 'slot') setFormError(effect.message)
      },
    })
  }

  const kindLine = [p.specialties.map(specialtyLabel).join(', ') || placeKindLabel(p.kind), placeAddress(p)].filter(Boolean).join(' · ')

  return (
    <div className="fixed inset-0 z-[85] flex items-end justify-center md:items-center md:p-6">
      <motion.div className="absolute inset-0 bg-black/50" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
      <motion.div
        role="dialog"
        aria-modal="true"
        aria-label={`${plan ? 'Plan a visit to' : 'Book an appointment at'} ${p.name}`}
        className="relative flex max-h-[94dvh] w-full max-w-lg flex-col overflow-hidden rounded-t-[1.75rem] bg-elev shadow-[var(--shadow-pop)] md:max-h-[90dvh] md:rounded-[1.75rem]"
        initial={{ y: '100%', opacity: 0.6 }}
        animate={{ y: 0, opacity: 1 }}
        exit={{ y: '100%', opacity: 0 }}
        transition={{ type: 'spring', stiffness: 380, damping: 38 }}
      >
        {/* header */}
        <div className="flex items-center gap-3 border-b border-line px-5 py-4">
          <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-accent-soft text-accent-text">{p.kind === 'doctor' ? <Stethoscope className="size-6" aria-hidden /> : p.kind === 'hospital' ? <Hospital className="size-6" aria-hidden /> : <Building2 className="size-6" aria-hidden />}</span>
          <div className="min-w-0 flex-1">
            <h2 className="truncate font-bold">{p.name}</h2>
            <p className="truncate text-sm text-muted">{kindLine}</p>
          </div>
          <IconButton label="Close" size="sm" onClick={onClose}>
            <X className="size-4" />
          </IconButton>
        </div>

        {stage === 'done' && booked ? (
          <Success appt={booked} place={p} onClose={onClose} onCarePlan={() => { onClose(); navigate('/appointments') }} />
        ) : (
          <>
            <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-5 scroll-thin">
              {plan ? (
                <div className="flex items-start gap-2.5 rounded-2xl bg-saffron-soft px-3.5 py-3 text-sm text-saffron-text" role="note">
                  <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <p className="font-semibold">Plan a visit</p>
                    <p>This place does not take online bookings. We save the time you choose in your Care Plan and remind you. {NOT_CONFIRMED}</p>
                    {phoneHref && p.phone && (
                      <a href={phoneHref} className="inline-flex min-h-11 items-center gap-1.5 rounded-xl bg-elev px-3.5 font-semibold text-accent-text">
                        <Phone className="size-4" aria-hidden /> Call {p.phone}
                      </a>
                    )}
                  </div>
                </div>
              ) : null}

              <section aria-labelledby="bk-for" className="space-y-2">
                <SectionLabel id="bk-for">{plan ? 'Visit for' : 'Booking for'}</SectionLabel>
                <div role="radiogroup" aria-labelledby="bk-for" className="flex flex-wrap gap-2">
                  <WhoChip active={forId === 'me'} onClick={() => chooseWho('me')}>Myself</WhoChip>
                  {(family.data ?? []).map((m) => (
                    <WhoChip key={m.id} active={forId === m.id} onClick={() => chooseWho(m.id)}>
                      {m.name.split(/\s+/)[0]} <span className="font-normal opacity-80">({relationLabel(m.relation).toLowerCase()})</span>
                    </WhoChip>
                  ))}
                  <button type="button" onClick={() => { onClose(); navigate('/family') }} className="inline-flex min-h-11 items-center gap-1.5 rounded-full border border-dashed border-accent/60 px-3.5 text-sm font-semibold text-accent-text transition hover:bg-accent-soft">
                    <UserPlus className="size-4" aria-hidden /> Add a family member
                  </button>
                </div>
                {family.isError && <p className="text-xs text-muted">Your family list could not be loaded, so you can only choose yourself right now.</p>}
              </section>

              {!plan && (
                <section aria-labelledby="bk-format" className="space-y-2">
                  <SectionLabel id="bk-format">Visit format</SectionLabel>
                  <div role="radiogroup" aria-labelledby="bk-format" className="grid grid-cols-2 gap-2 rounded-2xl bg-soft p-1">
                    <FormatButton active={mode === 'in_person'} onClick={() => setMode('in_person')} icon={<Building2 className="size-4" aria-hidden />}>In person</FormatButton>
                    <FormatButton active={mode === 'teleconsultation'} disabled={!teleOk} onClick={() => setMode('teleconsultation')} icon={<Video className="size-4" aria-hidden />}>
                      Video visit
                    </FormatButton>
                  </div>
                  {avail.data && !teleOk && <p className="text-xs text-muted">This clinic does not offer video visits.</p>}
                </section>
              )}

              {plan ? (
                <section aria-labelledby="bk-when" className="space-y-2">
                  <SectionLabel id="bk-when">When do you plan to go? (India time)</SectionLabel>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div>
                      <label htmlFor={ids.date} className="mb-1 block text-sm font-medium">Date</label>
                      <input
                        id={ids.date}
                        type="date"
                        value={planDate}
                        min={bounds.min}
                        max={bounds.max}
                        onChange={(e) => { setPlanDate(e.target.value); setErrors((c) => ({ ...c, slot: undefined })) }}
                        aria-invalid={!!errors.slot}
                        className={cn(field, 'h-12')}
                      />
                    </div>
                    <div>
                      <label htmlFor={ids.time} className="mb-1 block text-sm font-medium">Time</label>
                      <input
                        id={ids.time}
                        type="time"
                        value={planTime}
                        step={300}
                        onChange={(e) => { setPlanTime(e.target.value); setErrors((c) => ({ ...c, slot: undefined })) }}
                        aria-invalid={!!errors.slot}
                        className={cn(field, 'h-12')}
                      />
                    </div>
                  </div>
                  <p className="text-xs text-muted">Choose a time at least 2 hours from now and within 60 days.</p>
                </section>
              ) : (
                <>
                  <section aria-labelledby="bk-date" className="space-y-2">
                    <SectionLabel id="bk-date">Choose a date</SectionLabel>
                    {avail.isLoading ? (
                      <Skeleton className="h-20" />
                    ) : avail.isError ? (
                      <div role="alert" className="flex items-center justify-between gap-3 rounded-2xl bg-danger-soft px-4 py-3 text-sm text-danger">
                        Could not load the available times.
                        <Button size="sm" onClick={() => void avail.refetch()}>Retry</Button>
                      </div>
                    ) : days.length === 0 ? (
                      <p className="rounded-2xl bg-soft px-4 py-3 text-sm text-muted">No open times in the next few days. Please try another place.</p>
                    ) : (
                      <div role="radiogroup" aria-labelledby="bk-date" className="no-scrollbar -mx-5 flex gap-2 overflow-x-auto px-5 pb-1">
                        {days.map((d) => {
                          const active = d.key === activeDay
                          return (
                            <button
                              key={d.key}
                              role="radio"
                              aria-checked={active}
                              aria-label={`${formatSlotDate(d.key)}, ${d.count} ${d.count === 1 ? 'slot' : 'slots'}`}
                              onClick={() => { setDay(d.key); setTime(null); setErrors((c) => ({ ...c, slot: undefined })) }}
                              className={cn(
                                'flex min-h-[5.25rem] w-[4.75rem] shrink-0 flex-col items-center justify-center rounded-2xl border px-2 py-2 transition',
                                active ? 'border-accent bg-accent text-accent-fg shadow-sm' : 'border-line bg-elev hover:border-accent/40 hover:bg-soft',
                              )}
                            >
                              <span className={cn('text-[11px] font-semibold uppercase', active ? 'text-accent-fg/85' : 'text-muted')}>{d.label}</span>
                              <span className="text-xl leading-tight font-bold">{d.dayNumber}</span>
                              <span className={cn('text-[11px]', active ? 'text-accent-fg/85' : 'text-muted')}>{d.count} {d.count === 1 ? 'slot' : 'slots'}</span>
                            </button>
                          )
                        })}
                      </div>
                    )}
                  </section>

                  {groups.length > 0 && (
                    <section aria-labelledby="bk-time" className="space-y-3">
                      <SectionLabel id="bk-time">Choose a time (IST)</SectionLabel>
                      {groups.map((g) => (
                        <div key={g.period}>
                          <div className="mb-1.5 text-xs font-semibold text-muted">{g.label}</div>
                          <div role="radiogroup" aria-label={`${g.label} times`} className="flex flex-wrap gap-2">
                            {g.times.map((t) => (
                              <button
                                key={t}
                                role="radio"
                                aria-checked={time === t}
                                onClick={() => { setTime(t); setErrors((c) => ({ ...c, slot: undefined })); setFormError(null) }}
                                className={cn(
                                  'min-h-11 rounded-full border px-3.5 text-sm font-medium tabular-nums transition',
                                  time === t ? 'border-accent bg-accent text-accent-fg' : 'border-line bg-elev hover:border-accent/40 hover:bg-soft',
                                )}
                              >
                                {formatSlotTime(t)}
                              </button>
                            ))}
                          </div>
                        </div>
                      ))}
                    </section>
                  )}
                </>
              )}
              {errors.slot && <p role="alert" className="text-sm font-medium text-danger">{errors.slot}</p>}

              <section className="space-y-1.5">
                <label htmlFor={ids.reason} className="label-caps block">Reason for visit</label>
                <textarea
                  id={ids.reason}
                  value={reason}
                  maxLength={300}
                  rows={3}
                  onChange={(e) => { setReason(e.target.value); setErrors((c) => ({ ...c, reason: undefined })) }}
                  placeholder="For example: fever and sore throat since yesterday"
                  aria-invalid={!!errors.reason}
                  aria-describedby={errors.reason ? `${ids.reason}-e` : undefined}
                  className={cn(field, 'resize-none py-3')}
                />
                {errors.reason && <p id={`${ids.reason}-e`} role="alert" className="text-sm font-medium text-danger">{errors.reason}</p>}
              </section>

              <div className="grid gap-4 sm:grid-cols-2">
                <section className="space-y-1.5">
                  <label htmlFor={ids.name} className="label-caps block">Patient name</label>
                  <input id={ids.name} value={name} maxLength={80} autoComplete="name" onChange={(e) => { setName(e.target.value); setErrors((c) => ({ ...c, name: undefined })) }} aria-invalid={!!errors.name} aria-describedby={errors.name ? `${ids.name}-e` : undefined} className={cn(field, 'h-12')} />
                  {errors.name && <p id={`${ids.name}-e`} role="alert" className="text-sm font-medium text-danger">{errors.name}</p>}
                </section>
                <section className="space-y-1.5">
                  <label htmlFor={ids.mobile} className="label-caps block">Mobile number</label>
                  <input id={ids.mobile} value={mobile} inputMode="tel" autoComplete="tel" placeholder="10-digit number" maxLength={16} onChange={(e) => { setMobile(e.target.value); setErrors((c) => ({ ...c, mobile: undefined })) }} aria-invalid={!!errors.mobile} aria-describedby={errors.mobile ? `${ids.mobile}-e` : undefined} className={cn(field, 'h-12')} />
                  {errors.mobile && <p id={`${ids.mobile}-e`} role="alert" className="text-sm font-medium text-danger">{errors.mobile}</p>}
                </section>
              </div>

              {formError && (
                <div role="alert" className="flex items-start gap-2 rounded-2xl border border-danger/30 bg-danger-soft px-3.5 py-3 text-sm text-danger">
                  <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                  <span className="min-w-0 flex-1">{formError}</span>
                </div>
              )}
            </div>

            <div className="border-t border-line bg-elev px-5 pt-3 pb-[max(1rem,env(safe-area-inset-bottom))]">
              <p className="mb-2.5 min-h-5 text-center text-sm text-muted" aria-live="polite">
                {summary ?? (plan ? 'Pick a date and time to continue.' : 'Pick a date and time to continue.')}
              </p>
              <Button variant="primary" size="lg" className="w-full" onClick={review} disabled={!plan && days.length === 0 && !avail.isLoading}>
                {plan ? 'Save this visit' : 'Review and confirm'}
              </Button>
            </div>
          </>
        )}
      </motion.div>

      <Dialog
        open={confirming}
        onClose={() => !book.isPending && setConfirming(false)}
        title={plan ? 'Save this visit?' : 'Confirm your appointment'}
        footer={
          <>
            <Button variant="secondary" disabled={book.isPending} onClick={() => setConfirming(false)}>Go back</Button>
            <Button variant="primary" loading={book.isPending} onClick={submit}>{plan ? 'Save this visit' : 'Confirm booking'}</Button>
          </>
        }
      >
        {slot && (
          <div className="space-y-3 text-fg">
            <p className="text-muted">{plan ? NOT_CONFIRMED : 'Please check these details. When you confirm, this appointment will be booked.'}</p>
            <dl className="space-y-2 rounded-2xl bg-soft/70 p-3.5 text-sm">
              <Row label="Where">{whereLabel(p, form.mode)}</Row>
              <Row label="When">{formatSlotDate(slot.date)}, {formatSlotTime(slot.time)} IST</Row>
              {!plan && <Row label="Format">{mode === 'teleconsultation' ? 'Video visit' : 'In person'}</Row>}
              <Row label="Patient">{name.trim()}, {mobile.trim()}{member && <span className="block text-xs font-normal text-muted">Family member ({relationLabel(member.relation).toLowerCase()})</span>}</Row>
              <Row label="Reason">{reason.trim()}</Row>
              {!plan && typeof fee === 'number' && fee > 0 && <Row label="Listed fee">₹{fee}</Row>}
            </dl>
          </div>
        )}
      </Dialog>
    </div>
  )
}

function WhoChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      onClick={onClick}
      className={cn('inline-flex min-h-11 items-center gap-1 rounded-full border px-3.5 text-sm font-semibold transition', active ? 'border-accent bg-accent text-accent-fg' : 'border-line bg-elev hover:border-accent/40 hover:bg-soft')}
    >
      {children}
    </button>
  )
}

function FormatButton({ active, disabled, onClick, icon, children }: { active: boolean; disabled?: boolean; onClick: () => void; icon: ReactNode; children: ReactNode }) {
  return (
    <button
      role="radio"
      aria-checked={active}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'flex min-h-11 items-center justify-center gap-1.5 rounded-xl text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-45',
        active ? 'bg-elev text-accent-text shadow-sm' : 'text-muted hover:text-fg',
      )}
    >
      {icon}
      {children}
    </button>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <dt className="w-16 shrink-0 text-muted">{label}</dt>
      <dd className="min-w-0 flex-1 font-medium break-words">{children}</dd>
    </div>
  )
}

function Success({ appt, place: p, onClose, onCarePlan }: { appt: Appointment; place: Place; onClose: () => void; onCarePlan: () => void }) {
  const tele = appt.mode === 'teleconsultation'
  const confirmed = appt.clinic_confirmed !== false
  const phone = appt.provider?.phone ?? p.phone
  const phoneHref = telLinkFor(phone)
  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-5 py-6 scroll-thin">
      <div className="flex flex-col items-center text-center">
        <span className={cn('mb-3 grid size-16 place-items-center rounded-full', confirmed ? 'bg-ok-soft text-ok' : 'bg-saffron-soft text-saffron-text')}>
          <CheckCircle2 className="size-9" aria-hidden />
        </span>
        <h3 className="text-xl font-bold" role="status">{confirmed ? 'Appointment booked' : 'Visit saved'}</h3>
        <div className="mt-1.5"><ConfirmationBadge confirmed={confirmed} /></div>
        <p className="mt-3 text-sm text-muted">Your reference</p>
        <div className="mt-1.5"><CopyChip value={appt.ref} /></div>
      </div>

      {!confirmed && (
        <div className="mt-5 space-y-2.5 rounded-2xl bg-saffron-soft px-4 py-3.5 text-sm text-saffron-text" role="note">
          <p className="font-semibold">{NOT_CONFIRMED}</p>
          <div className="flex flex-wrap gap-2">
            {phoneHref && phone ? (
              <a href={phoneHref} className="inline-flex h-12 items-center gap-2 rounded-2xl bg-accent px-5 font-semibold text-accent-fg hover:brightness-110">
                <Phone className="size-5" aria-hidden /> Call to confirm
              </a>
            ) : (
              <p>No phone number is listed for this place. Visit in person or look it up before you go.</p>
            )}
            {Number.isFinite(p.lat) && Number.isFinite(p.lon) && (
              <a href={directionsLink(p.lat, p.lon)} target="_blank" rel="noopener noreferrer" className="inline-flex h-12 items-center gap-2 rounded-2xl border border-line bg-elev px-5 font-semibold text-fg">
                <Route className="size-5" aria-hidden /> Get directions
              </a>
            )}
          </div>
        </div>
      )}

      <dl className="mt-5 space-y-2.5 rounded-2xl bg-soft/70 p-4 text-sm">
        <div className="flex items-start gap-2.5">
          <CalendarCheck className="mt-0.5 size-4 shrink-0 text-accent-text" aria-hidden />
          <div><dt className="sr-only">When</dt><dd className="font-semibold">{formatIST(appt.starts_at)}</dd></div>
        </div>
        <div className="flex items-start gap-2.5">
          {tele ? <Video className="mt-0.5 size-4 shrink-0 text-accent-text" aria-hidden /> : <MapPin className="mt-0.5 size-4 shrink-0 text-accent-text" aria-hidden />}
          <div><dt className="sr-only">Where</dt><dd className="font-semibold">{appt.provider.doctor_name ?? appt.provider.name}</dd><dd className="text-muted">{tele ? 'Video visit (online)' : placeAddress(p) || p.city}</dd></div>
        </div>
      </dl>

      <p className="mt-4 text-sm text-muted">We will remind you in the app the day before and about 2 hours before your visit. You can see and manage it in Care Plan.</p>

      <div className="mt-6 grid gap-2.5">
        <Button variant="primary" size="lg" onClick={onCarePlan}>View in Care Plan</Button>
        <Button variant="secondary" onClick={onClose}>Done</Button>
      </div>
    </div>
  )
}
