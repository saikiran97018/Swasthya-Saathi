import { istDateKey } from './time'

export type Period = 'morning' | 'afternoon' | 'evening'

export const PERIOD_LABEL: Record<Period, string> = { morning: 'Morning', afternoon: 'Afternoon', evening: 'Evening' }

/** Before 12:00 morning, 12:00-16:59 afternoon, 17:00 onwards evening (clinic local time, IST). */
export function periodOf(hhmm: string): Period {
  const h = Number(hhmm.split(':')[0])
  return h < 12 ? 'morning' : h < 17 ? 'afternoon' : 'evening'
}

export interface SlotGroup {
  period: Period
  label: string
  times: string[]
}

/** Groups HH:MM slots into Morning / Afternoon / Evening, keeping their order and dropping empty groups. */
export function groupSlotsByPeriod(times: string[]): SlotGroup[] {
  return (['morning', 'afternoon', 'evening'] as const)
    .map((period) => ({ period, label: PERIOD_LABEL[period], times: times.filter((t) => periodOf(t) === period) }))
    .filter((g) => g.times.length > 0)
}

export interface DayOption {
  /** YYYY-MM-DD, the key to look the slots up with. */
  key: string
  /** "Today", "Tomorrow", or a short weekday such as "Fri". */
  label: string
  dayNumber: string
  count: number
}

const utcDay = (key: string) => Date.UTC(+key.slice(0, 4), +key.slice(5, 7) - 1, +key.slice(8, 10))
const WEEKDAY = new Intl.DateTimeFormat('en-IN', { timeZone: 'UTC', weekday: 'short' })

/** The date strip: only days that have free slots, oldest first, with a friendly label and the slot count. */
export function dayOptions(open: Record<string, string[]>, now: Date = new Date()): DayOption[] {
  const today = istDateKey(now)
  return Object.entries(open)
    .filter(([, times]) => Array.isArray(times) && times.length > 0)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, times]) => {
      const diff = Math.round((utcDay(key) - utcDay(today)) / 86_400_000)
      const label = diff === 0 ? 'Today' : diff === 1 ? 'Tomorrow' : WEEKDAY.format(new Date(utcDay(key) + 12 * 3_600_000))
      return { key, label, dayNumber: String(Number(key.slice(8, 10))), count: times.length }
    })
}

/** The slot string the booking API expects: "YYYY-MM-DD HH:MM" (IST), exactly as the availability endpoint returned it. */
export function slotParam(date: string, time: string): string {
  return `${date} ${time}`
}
