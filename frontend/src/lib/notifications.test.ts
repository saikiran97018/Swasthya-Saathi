import { describe, expect, it } from 'vitest'
import type { AppNotification } from '@/api/types'
import { appointmentPrompts, newUnread, notificationPrefill, notificationTarget } from './notifications'

const n = (over: Partial<AppNotification> & { id: string }): AppNotification => ({
  kind: 'appointment_reminder', title: 'Reminder', message: 'Your appointment is tomorrow', language: 'en', appointment_ref: 'AP-7K3QX',
  conversation_id: 'conv-1', delivered_at: '2026-11-22T10:00:00Z', read_at: null, ...over,
})

describe('newUnread (poll diff)', () => {
  it('never reports anything on the first load, so old reminders are not toasted on page open', () => {
    expect(newUnread(null, [n({ id: 'a' }), n({ id: 'b' })])).toEqual([])
  })

  it('reports only unread items it has not seen, newest first', () => {
    const seen = new Set(['a'])
    const items = [
      n({ id: 'a' }),
      n({ id: 'b', delivered_at: '2026-11-22T10:05:00Z' }),
      n({ id: 'c', delivered_at: '2026-11-22T10:09:00Z' }),
      n({ id: 'd', delivered_at: '2026-11-22T10:07:00Z', read_at: '2026-11-22T10:08:00Z' }), // already read elsewhere
    ]
    expect(newUnread(seen, items).map((x) => x.id)).toEqual(['c', 'b'])
  })

  it('reports nothing when nothing changed', () => {
    const items = [n({ id: 'a' }), n({ id: 'b' })]
    expect(newUnread(new Set(['a', 'b']), items)).toEqual([])
  })
})

describe('opening a notification', () => {
  it('prefills the composer (never auto-sends) according to the kind', () => {
    expect(notificationPrefill(n({ id: 'x', kind: 'feedback_request' }))).toBe('Feedback for my appointment AP-7K3QX: ')
    expect(notificationPrefill(n({ id: 'x', kind: 'follow_up' }))).toBe("I'd like to book my follow-up visit for appointment AP-7K3QX")
    expect(notificationPrefill(n({ id: 'x', kind: 'appointment_reminder' }))).toBeNull()
  })

  it('still prefills sensibly when the reference is missing', () => {
    expect(notificationPrefill({ kind: 'feedback_request', appointment_ref: null })).toBe('Feedback for my appointment: ')
    expect(notificationPrefill({ kind: 'follow_up', appointment_ref: null })).toBe("I'd like to book my follow-up visit")
  })

  it('navigates to the conversation, or a new chat when there is none', () => {
    expect(notificationTarget({ conversation_id: 'abc' })).toBe('/chat/abc')
    expect(notificationTarget({ conversation_id: null })).toBe('/chat')
  })

  it('builds the appointment action prompts', () => {
    expect(appointmentPrompts.reschedule('AP-1')).toBe('I want to reschedule appointment AP-1')
    expect(appointmentPrompts.feedback('AP-1')).toBe('Feedback for my appointment AP-1: ')
    expect(appointmentPrompts.bookWithProvider('Demo Family Clinic', 'HC-GNT-01')).toBe('Book an appointment at Demo Family Clinic (HC-GNT-01)')
  })
})
