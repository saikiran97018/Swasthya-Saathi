/**
 * Doctor ratings come only from real patient feedback. Until a provider has at least one rating nothing is shown:
 * no placeholder stars, no invented scores.
 */
export interface Rated {
  rating_avg?: number | null
  rating_count?: number | null
}

/** "4.9 (24 reviews)" or null when there is nothing real to show. */
export function ratingLabel(p: Rated): string | null {
  const count = p.rating_count ?? 0
  const avg = p.rating_avg
  if (!Number.isFinite(count) || count <= 0) return null
  if (avg === null || avg === undefined || !Number.isFinite(avg) || avg < 1 || avg > 5) return null
  // Round half up on the decimal value: 4.85.toFixed(1) is "4.8" because of how 4.85 is stored in binary.
  const score = (Math.round((avg + Number.EPSILON) * 10) / 10).toFixed(1)
  return `${score} (${count} ${count === 1 ? 'review' : 'reviews'})`
}
