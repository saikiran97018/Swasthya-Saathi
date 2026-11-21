// Thin wrapper around the Agora Web SDK. This is the ONLY file that touches `agora-rtc-sdk-ng`, and the SDK is
// loaded with a dynamic import when a call starts, so it stays out of the main bundle.
// Everything above it (callSession.ts, the page) talks to the CallTransport interface and is tested with a fake.
import type { IAgoraRTCClient, IAgoraRTCRemoteUser, IMicrophoneAudioTrack } from 'agora-rtc-sdk-ng'
import { CallFailure, classifyMicError } from './callState'
import type { CallTransport, JoinCredentials, TransportHandlers } from './callSession'

/** Agora "exception" codes worth telling the user about (others are informational). */
const AUDIO_INPUT_LEVEL_TOO_LOW = 2001

export function createAgoraTransport(handlers: TransportHandlers): CallTransport {
  let client: IAgoraRTCClient | null = null
  let mic: IMicrophoneAudioTrack | null = null
  let left = false

  const loadSdk = async () => (await import('agora-rtc-sdk-ng')).default

  return {
    async prepareMic() {
      const AgoraRTC = await loadSdk()
      AgoraRTC.setLogLevel(2) // warnings and errors only
      try {
        mic = await AgoraRTC.createMicrophoneAudioTrack({ AEC: true, ANS: true, AGC: true })
      } catch (err) {
        const e = classifyMicError(err)
        throw new CallFailure(e.kind, e.message)
      }
    },

    async join({ appId, channel, token, uid, agentUid }: JoinCredentials) {
      const AgoraRTC = await loadSdk()
      if (!mic) throw new CallFailure('mic_missing', 'The microphone is not ready. Please try again.')
      const c = AgoraRTC.createClient({ mode: 'rtc', codec: 'vp8' })
      client = c

      c.on('user-published', async (user: IAgoraRTCRemoteUser, mediaType) => {
        if (mediaType !== 'audio') return
        try {
          await c.subscribe(user, 'audio')
          user.audioTrack?.play()
        } catch {
          handlers.onNotice('We could not play the assistant’s voice. Check your speakers and try again.')
        }
      })
      c.on('user-left', (user: IAgoraRTCRemoteUser) => {
        if (user.uid === agentUid) handlers.onAgentLeft()
      })
      c.on('volume-indicator', (vols: { uid: number | string; level: number }[]) => {
        let remote = 0
        let local: number | null = null
        for (const v of vols) {
          if (String(v.uid) === String(uid)) local = v.level
          else remote = Math.max(remote, v.level)
        }
        handlers.onVolume(local ?? Math.round((mic?.getVolumeLevel() ?? 0) * 100), remote)
      })
      c.on('connection-state-change', (cur: string) => {
        if (left) return
        if (cur === 'RECONNECTING') handlers.onConnection('reconnecting')
        else if (cur === 'CONNECTED') handlers.onConnection('connected')
        else if (cur === 'DISCONNECTED') handlers.onConnection('disconnected')
      })
      c.on('exception', (evt: { code: number }) => {
        if (evt.code === AUDIO_INPUT_LEVEL_TOO_LOW) handlers.onNotice('We can barely hear your microphone. Move closer or check it is not covered.')
      })

      try {
        await c.join(appId, channel, token, uid)
        c.enableAudioVolumeIndicator()
        await c.publish(mic)
      } catch {
        await this.leave()
        throw new CallFailure('join_failed', 'We could not connect the call. Check your internet and try again.')
      }
    },

    async setMuted(muted) {
      await mic?.setEnabled(!muted)
    },

    async leave() {
      if (left) return
      left = true
      const c = client
      const m = mic
      client = null
      mic = null
      try {
        if (c && m) await c.unpublish(m)
      } catch {
        /* already gone */
      }
      try {
        m?.stop()
        m?.close()
      } catch {
        /* already closed */
      }
      try {
        c?.removeAllListeners()
        await c?.leave()
      } catch {
        /* already left */
      }
    },
  }
}
