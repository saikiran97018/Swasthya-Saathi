import { useCallback, useSyncExternalStore } from 'react'
import { api } from '@/api/endpoints'
import type { Message } from '@/api/types'
import { findLanguage, ttsAvailable } from '@/lib/language'
import { speechPlayer, type PlayerSnapshot } from '@/lib/speechPlayer'
import { LIVE_REPLY_ID } from '@/lib/speechStreamer'
import { recallAudio, rememberAudio } from '@/lib/ttsCache'
import { useLanguage } from './LanguageProvider'
import { usePrefs } from '@/api/hooks'

export interface SpeechApi {
  snapshot: PlayerSnapshot
  /** True if this message's audio is the one currently loading / playing / paused. */
  isActive: (message: Pick<Message, 'id'>, isLatestAssistant?: boolean) => boolean
  speakMessage: (message: Pick<Message, 'id' | 'content' | 'language'>, fallbackLanguage?: string | null) => void
  stop: () => void
  pause: () => void
  resume: () => void
  /** Whether we can speak this language at all. */
  canSpeak: (language: string | null | undefined) => boolean
}

/** Shared access to the one speech player: play/replay a message, stop, pause. */
export function useSpeech(): SpeechApi {
  const snapshot = useSyncExternalStore(speechPlayer.subscribe, speechPlayer.getSnapshot)
  const { languages } = useLanguage()
  const { data: prefs } = usePrefs()

  const canSpeak = useCallback((language: string | null | undefined) => ttsAvailable(language, languages), [languages])

  const speakMessage = useCallback<SpeechApi['speakMessage']>(
    (message, fallbackLanguage) => {
      const language = findLanguage(message.language ?? fallbackLanguage ?? undefined, languages)?.code ?? 'en'
      speechPlayer.stop()
      const cached = recallAudio(message.id)
      if (cached) {
        cached.forEach((blob) => speechPlayer.enqueue(message.id, blob))
        return
      }
      const blob = api.synthesize(message.content, language, prefs?.tts_gender)
      rememberAudio(message.id, [blob])
      speechPlayer.enqueue(message.id, blob)
    },
    [languages, prefs?.tts_gender],
  )

  const isActive = useCallback<SpeechApi['isActive']>(
    (message, isLatestAssistant) => {
      if (snapshot.status === 'idle' || !snapshot.messageId) return false
      return snapshot.messageId === message.id || (!!isLatestAssistant && snapshot.messageId === LIVE_REPLY_ID)
    },
    [snapshot],
  )

  return { snapshot, isActive, speakMessage, canSpeak, stop: () => speechPlayer.stop(), pause: () => speechPlayer.pause(), resume: () => speechPlayer.resume() }
}
