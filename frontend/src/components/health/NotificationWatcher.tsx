import { useEffect, useRef } from 'react'
import { api } from '@/api/endpoints'
import { useNotifications, usePrefs } from '@/api/hooks'
import { useToast } from '@/components/ui/Toast'
import { useLanguage } from '@/hooks/LanguageProvider'
import { ttsAvailable } from '@/lib/language'
import { newUnread } from '@/lib/notifications'
import { speechPlayer } from '@/lib/speechPlayer'

/**
 * Renders nothing. While the app is open, watches the polled notifications: when new unread ones
 * arrive it shows a toast and (if voice output is on) reads the newest aloud in its own language.
 */
export function NotificationWatcher() {
  const toast = useToast()
  const { data } = useNotifications()
  const { data: prefs } = usePrefs()
  const { languages } = useLanguage()
  const seen = useRef<Set<string> | null>(null) // null until the first response: don't toast old reminders on page load

  useEffect(() => {
    if (!data) return
    const fresh = newUnread(seen.current, data.items)
    seen.current = new Set(data.items.map((n) => n.id))
    const newest = fresh[0]
    if (!newest) return

    // The message is already a complete sentence in the user's language; the title would just repeat it.
    toast.info(newest.message || newest.title)

    if (prefs?.voice_output_enabled && ttsAvailable(newest.language, languages) && document.visibilityState === 'visible') {
      // Queued behind anything already being spoken rather than cutting it off.
      speechPlayer.enqueue(`notification-${newest.id}`, api.synthesize(newest.message, newest.language, prefs.tts_gender))
    }
  }, [data, prefs?.voice_output_enabled, prefs?.tts_gender, languages, toast])

  return null
}
