import type { AppNotification } from '@/api/types'

/**
 * Notifications that are unread and that we have not shown before, newest first.
 * `seen === null` means this is the first load: nothing counts as new (don't toast old reminders on page open).
 */
export function newUnread(seen: ReadonlySet<string> | null, items: AppNotification[]): AppNotification[] {
  if (seen === null) return []
  return items
    .filter((n) => !n.read_at && !seen.has(n.id))
    .sort((a, b) => new Date(b.delivered_at).getTime() - new Date(a.delivered_at).getTime())
}

/** Text to put in the composer (never auto-sent) when a notification is opened. */
export function notificationPrefill(n: Pick<AppNotification, 'kind' | 'appointment_ref'>): string | null {
  const ref = n.appointment_ref
  if (n.kind === 'feedback_request') return ref ? `Feedback for my appointment ${ref}: ` : 'Feedback for my appointment: '
  if (n.kind === 'follow_up') return ref ? `I'd like to book my follow-up visit for appointment ${ref}` : "I'd like to book my follow-up visit"
  if (n.kind === 'symptom_checkin') return 'Update on how I am feeling: '
  if (n.kind === 'vaccine') return 'I want to plan a visit for the vaccines that are due'
  return null // reminders just open the conversation
}

/** Where a notification leads: its conversation, or a fresh chat when it has none. */
export function notificationTarget(n: Pick<AppNotification, 'conversation_id'>): string {
  return n.conversation_id ? `/chat/${n.conversation_id}` : '/chat'
}

export const appointmentPrompts = {
  reschedule: (ref: string) => `I want to reschedule appointment ${ref}`,
  feedback: (ref: string) => `Feedback for my appointment ${ref}: `,
  bookNew: () => 'I would like to book a doctor appointment.',
  bookWithProvider: (name: string, code: string) => `Book an appointment at ${name} (${code})`,
}
