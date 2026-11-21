/**
 * All appointment times are shown in Indian Standard Time, whatever timezone the browser is in.
 * The backend sends instants as ISO-8601 UTC and slot times as local IST strings ("2026-11-23", "10:20").
 */
export const IST = 'Asia/Kolkata'

const fmt = (opts: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat('en-IN', { timeZone: IST, ...opts })

const DATE_LONG = fmt({ weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })
const TIME = fmt({ hour: 'numeric', minute: '2-digit', hour12: true })
const KEY = new Intl.DateTimeFormat('en-CA', { timeZone: IST, year: 'numeric', month: '2-digit', day: '2-digit' })

const asDate = (v: string | Date) => (v instanceof Date ? v : new Date(v))

/** "Mon, 23 Nov 2026" in IST. (Built from parts: en-IN's own pattern puts a stray comma before the year.) */
export function istDate(v: string | Date): string {
  const p = DATE_LONG.formatToParts(asDate(v))
  const get = (t: string) => p.find((x) => x.type === t)?.value ?? ''
  return `${get('weekday')}, ${get('day')} ${get('month')} ${get('year')}`
}

/** "10:00 am" in IST. */
export function istTime(v: string | Date): string {
  return TIME.format(asDate(v))
}

/** "Mon, 23 Nov 2026, 10:00 am IST": always labelled so nobody reads it as local time. */
export function formatIST(v: string | Date): string {
  return `${istDate(v)}, ${istTime(v)} IST`
}

const DAY_PARTS = fmt({ day: 'numeric', month: 'short' })

/** { day: '23', month: 'Nov' } in IST, for calendar-style date badges. */
export function istDayMonth(v: string | Date): { day: string; month: string } {
  const parts = DAY_PARTS.formatToParts(asDate(v))
  return { day: parts.find((p) => p.type === 'day')?.value ?? '', month: parts.find((p) => p.type === 'month')?.value ?? '' }
}

/** "Sat" in IST, for calendar-style date badges. */
export function istWeekday(v: string | Date): string {
  return fmt({ weekday: 'short' }).format(asDate(v))
}

/** The IST calendar date of an instant as YYYY-MM-DD (so 19:00Z on the 22nd is the 23rd in India). */
export function istDateKey(v: string | Date): string {
  return KEY.format(asDate(v))
}

/** "Today" / "Tomorrow" / "Yesterday" in IST, or null when further away. */
export function relativeDayIST(v: string | Date, now: Date = new Date()): 'Today' | 'Tomorrow' | 'Yesterday' | null {
  const day = (k: string) => Date.UTC(+k.slice(0, 4), +k.slice(5, 7) - 1, +k.slice(8, 10))
  const diff = Math.round((day(istDateKey(v)) - day(istDateKey(now))) / 86_400_000)
  return diff === 0 ? 'Today' : diff === 1 ? 'Tomorrow' : diff === -1 ? 'Yesterday' : null
}

/** A YYYY-MM-DD slot date label, e.g. "Mon, 23 Nov". Built at UTC noon so no timezone can shift the day. */
export function formatSlotDate(key: string): string {
  const [y, m, d] = key.split('-').map(Number)
  if (!y || !m || !d) return key
  return new Intl.DateTimeFormat('en-IN', { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short' }).format(new Date(Date.UTC(y, m - 1, d, 12)))
}

/** "10:20" -> "10:20 am", "14:05" -> "2:05 pm". Anything that is not HH:MM is returned unchanged. */
export function formatSlotTime(hhmm: string): string {
  const m = /^(\d{1,2}):(\d{2})$/.exec(hhmm)
  if (!m) return hhmm
  const h = Number(m[1])
  const suffix = h >= 12 ? 'pm' : 'am'
  return `${h % 12 === 0 ? 12 : h % 12}:${m[2]} ${suffix}`
}

/** "Mon, 23 Nov at 10:20 am IST" for a next-available slot. */
export function formatNextAvailable(slot: { date: string; time: string } | null | undefined): string {
  return slot ? `${formatSlotDate(slot.date)}, ${formatSlotTime(slot.time)} IST` : 'No free slot soon'
}
