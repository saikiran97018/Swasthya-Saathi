import { useCallback, useEffect, useReducer, useRef } from 'react'
import { api, stopAgoraSessionKeepalive } from '@/api/endpoints'
import { createAgoraTransport } from '@/lib/agoraCall'
import { CallSession, type CallApi, type CallSessionDeps } from '@/lib/callSession'
import { callReducer, initialCallState } from '@/lib/callState'

const realApi: CallApi = {
  startSession: api.agoraStartSession,
  stopSession: api.agoraStopSession,
  stopSessionKeepalive: stopAgoraSessionKeepalive,
}

/** Dev-only seam so the UI can be driven in a browser without Agora credentials (see frontend/README.md). */
function devTransport(): CallSessionDeps['createTransport'] | null {
  if (!import.meta.env.DEV) return null
  return (window as unknown as { __fakeCallTransport?: CallSessionDeps['createTransport'] }).__fakeCallTransport ?? null
}

/** React binding for CallSession: state, start / end / mute, and automatic hang-up when the page goes away. */
export function useLiveCall() {
  const [state, dispatch] = useReducer(callReducer, initialCallState)
  const session = useRef<CallSession | null>(null)

  useEffect(() => {
    const s = new CallSession({ api: realApi, createTransport: (h) => (devTransport() ?? createAgoraTransport)(h) }, dispatch)
    session.current = s
    const onHide = () => s.dispose()
    window.addEventListener('pagehide', onHide)
    return () => {
      window.removeEventListener('pagehide', onHide)
      s.dispose()
      session.current = null
    }
  }, [])

  const start = useCallback((language: string, conversationId?: string | null) => void session.current?.start({ language, conversationId }), [])
  const end = useCallback(() => void session.current?.end('user'), [])
  const setMuted = useCallback((muted: boolean) => void session.current?.setMuted(muted), [])
  const reset = useCallback(() => dispatch({ type: 'reset' }), [])

  return { state, start, end, setMuted, reset }
}
