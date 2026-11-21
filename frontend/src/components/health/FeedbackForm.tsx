import { useState } from 'react'
import { Star } from 'lucide-react'
import { ApiError } from '@/api/client'
import { useSubmitFeedback } from '@/api/hooks'
import type { Appointment } from '@/api/types'
import { Button } from '@/components/ui/primitives'
import { useToast } from '@/components/ui/Toast'
import { cn } from '@/lib/format'
import { Stars } from './shared'

const FEEDBACK_ERRORS: Record<string, string> = {
  too_early: 'You can rate this visit once the appointment time has passed.',
  already_rated: 'You have already rated this visit.',
  not_active: 'Only a visit that took place can be rated.',
}

const RATING_WORD = ['', 'Poor', 'Fair', 'Good', 'Very good', 'Excellent']

/**
 * Rate a completed visit: five tappable stars and an optional comment. Once rated, shows the saved rating.
 * The rating is stored with the appointment and feeds the provider's rating in Doctors.
 */
export function FeedbackForm({ appointment: a }: { appointment: Appointment }) {
  const toast = useToast()
  const submit = useSubmitFeedback()
  const [rating, setRating] = useState(0)
  const [comment, setComment] = useState('')
  const [error, setError] = useState<string | null>(null)

  if (a.feedback_rating !== null) {
    return (
      <div className="rounded-2xl bg-soft/70 p-3.5">
        <div className="flex items-center gap-2 text-sm font-semibold"><Stars rating={a.feedback_rating} /> Thanks for your feedback</div>
        {a.feedback_comment && <p className="mt-1 text-sm break-words text-muted">“{a.feedback_comment}”</p>}
      </div>
    )
  }

  const send = () => {
    if (rating < 1) {
      setError('Tap a star to rate your visit.')
      return
    }
    setError(null)
    submit.mutate(
      { id: a.id, rating, comment: comment.trim() || undefined },
      {
        onSuccess: () => toast.success('Thank you. Your feedback was saved.'),
        onError: (e) => setError(e instanceof ApiError && FEEDBACK_ERRORS[e.code] ? (FEEDBACK_ERRORS[e.code] as string) : e instanceof Error ? e.message : 'Could not save your feedback.'),
      },
    )
  }

  return (
    <div className="space-y-3 rounded-2xl bg-soft/70 p-3.5">
      <div>
        <p className="text-sm font-semibold">How was your visit?</p>
        <div role="radiogroup" aria-label="Rate your visit" className="mt-1.5 flex items-center gap-1">
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              role="radio"
              aria-checked={rating === n}
              aria-label={`${n} ${n === 1 ? 'star' : 'stars'}, ${RATING_WORD[n]}`}
              onClick={() => { setRating(n); setError(null) }}
              className="grid size-11 place-items-center rounded-xl transition active:scale-90 hover:bg-elev"
            >
              <Star className={cn('size-7 transition', n <= rating ? 'fill-saffron text-saffron' : 'text-line')} aria-hidden />
            </button>
          ))}
          {rating > 0 && <span className="ml-1 text-sm font-medium text-muted">{RATING_WORD[rating]}</span>}
        </div>
      </div>
      <div>
        <label htmlFor={`fb-${a.id}`} className="sr-only">Comment (optional)</label>
        <textarea
          id={`fb-${a.id}`}
          value={comment}
          maxLength={500}
          rows={2}
          onChange={(e) => setComment(e.target.value)}
          placeholder="Anything you would like to add? (optional)"
          className="w-full resize-none rounded-2xl border border-line bg-elev px-3.5 py-2.5 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent/25"
        />
      </div>
      {error && <p role="alert" className="text-sm font-medium text-danger">{error}</p>}
      <Button size="sm" variant="primary" loading={submit.isPending} onClick={send}>Send feedback</Button>
    </div>
  )
}
