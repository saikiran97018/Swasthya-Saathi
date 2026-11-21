/** Short "time until" label for the next-appointment pill: "In 3 days", "Tomorrow", "In 2 h 10 min", "Starting now". */
export function countdownLabel(startsAt: string | Date, now: Date = new Date()): string {
  const diff = new Date(startsAt).getTime() - now.getTime()
  if (!Number.isFinite(diff)) return ''
  if (diff <= -3_600_000) return 'Started'
  if (diff <= 60_000) return 'Starting now'
  const minutes = Math.floor(diff / 60_000)
  if (minutes < 60) return `In ${minutes} min`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) {
    const rest = minutes % 60
    return rest ? `In ${hours} h ${rest} min` : `In ${hours} h`
  }
  const days = Math.floor(hours / 24)
  return days === 1 ? 'In 1 day' : `In ${days} days`
}
