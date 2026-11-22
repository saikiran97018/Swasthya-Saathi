import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '@/api/client'
import { api } from '@/api/endpoints'
import { useHealth } from '@/api/hooks'
import { maxRecordMs, MicError, micSupported, VoiceRecorder, type RecordingResult } from '@/lib/recorder'
import { speechPlayer } from '@/lib/speechPlayer'

export type DictationStatus = 'idle' | 'starting' | 'listening' | 'transcribing'

export interface DictationResult {
  text: string
  language: string
  durationSeconds: number
  reason: RecordingResult['reason']
}

interface Options {
  /** Language for speech recognition (read at the moment recording stops). */
  getLanguage: () => string
  silenceMs: number
  onResult: (r: DictationResult) => void
}

/** Friendly text for the failures a user can actually act on. */
export function describeSpeechError(err: unknown): string {
  if (err instanceof MicError) return err.message
  if (err instanceof ApiError) {
    if (err.code === 'bhashini_not_configured') return 'Speech recognition is not set up yet. Ask the administrator to add the Bhashini keys, or type your message.'
    if (err.code === 'no_speech' || err.code === 'unclear_speech') return "I couldn't hear anything. Please try again a little closer to the microphone."
    if (err.status === 413) return 'That recording was too long. Please speak in shorter pieces.'
    return err.message
  }
  return 'Something went wrong with speech recognition. Please try again or type your message.'
}

/**
 * Record from the microphone, auto-stop when the user goes quiet, and transcribe with Bhashini.
 * Starting to speak always interrupts any reply that is being read aloud.
 */
export function useDictation({ getLanguage, silenceMs, onResult }: Options) {
  const { data: health } = useHealth()
  const [status, setStatus] = useState<DictationStatus>('idle')
  const [level, setLevel] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [analyser, setAnalyser] = useState<AnalyserNode | null>(null)
  const recorder = useRef<VoiceRecorder | null>(null)
  const busy = useRef(false)
  const latest = useRef({ getLanguage, onResult })
  latest.current = { getLanguage, onResult }

  const finish = useCallback(async (reason: RecordingResult['reason']) => {
    const rec = recorder.current
    if (!rec || busy.current) return
    busy.current = true
    recorder.current = null
    setAnalyser(null)
    setStatus('transcribing')
    try {
      const result = await rec.stop(reason)
      if (!result.hadSpeech) {
        setError("I couldn't hear anything. Please try again a little closer to the microphone.")
        return
      }
      const language = latest.current.getLanguage()
      const out = await api.transcribe(result.blob, language)
      latest.current.onResult({ text: out.text, language: out.language, durationSeconds: out.duration_seconds, reason })
    } catch (err) {
      setError(describeSpeechError(err))
    } finally {
      busy.current = false
      setStatus('idle')
    }
  }, [])

  const start = useCallback(async () => {
    if (recorder.current || busy.current) return
    setError(null)
    speechPlayer.stop() // barge-in: the user talking cuts the assistant off
    setStatus('starting')
    const rec = new VoiceRecorder({ silenceMs, maxMs: maxRecordMs(health?.max_audio_seconds), onLevel: setLevel, onAutoStop: (reason) => void finish(reason) })
    recorder.current = rec
    try {
      await rec.start()
      if (recorder.current !== rec) return // cancelled while the mic was starting
      setAnalyser(rec.analyser)
      setStatus('listening')
    } catch (err) {
      recorder.current = null
      rec.cancel()
      setStatus('idle')
      setError(describeSpeechError(err))
    }
  }, [finish, silenceMs, health?.max_audio_seconds])

  const stop = useCallback(() => void finish('manual'), [finish])

  const cancel = useCallback(() => {
    recorder.current?.cancel()
    recorder.current = null
    setAnalyser(null)
    setLevel(0)
    setStatus('idle')
  }, [])

  useEffect(() => () => recorder.current?.cancel(), [])

  return { status, level, analyser, error, clearError: () => setError(null), supported: micSupported(), start, stop, cancel }
}
