import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { AudioLines, Info, MessageSquareText, Mic, MicOff, Phone, PhoneOff, TriangleAlert, WifiOff } from 'lucide-react'
import { qk, usePrefs, useAgoraStatus } from '@/api/hooks'
import { CallTranscript } from '@/components/voice/CallTranscript'
import { VoiceOrb } from '@/components/voice/VoiceOrb'
import { Waveform } from '@/components/voice/Waveform'
import { Button, Skeleton, ToggleChip } from '@/components/ui/primitives'
import { useLanguage } from '@/hooks/LanguageProvider'
import { useLiveCall } from '@/hooks/useLiveCall'
import { AUTO_LANGUAGE } from '@/lib/language'
import { callLanguages, createLevelAnalyser, END_REASON_TEXT, formatTimer, isCallLive, orbStateFor, pickCallLanguage, type CallState } from '@/lib/callState'

function statusCopy(s: CallState): { title: string; hint: string } {
  switch (s.phase) {
    case 'requesting_mic':
      return { title: 'Allow your microphone', hint: 'Your browser may ask for permission. Choose Allow.' }
    case 'starting':
    case 'connecting':
      return { title: 'Connecting…', hint: 'Putting your health assistant on the line' }
    case 'active':
      if (s.reconnecting) return { title: 'Reconnecting…', hint: 'Your connection dropped. Hold on a moment.' }
      if (s.activity === 'speaking') return { title: 'Saathi is speaking', hint: 'You can talk over it any time' }
      if (s.muted) return { title: 'You are muted', hint: 'Tap Unmute so Saathi can hear you' }
      if (s.activity === 'listening') return { title: 'Listening to you…', hint: 'Keep going, or pause when you are done' }
      return { title: 'Go ahead, I am listening', hint: 'Talk like you would on a phone call' }
    case 'ending':
      return { title: 'Ending call…', hint: 'Hanging up' }
    case 'ended':
      return { title: 'Call ended', hint: s.endReason ? END_REASON_TEXT[s.endReason] : '' }
    case 'error':
      return { title: 'Call could not start', hint: '' }
    default:
      return { title: 'Ready when you are', hint: 'Choose your language, then start the call' }
  }
}

function Notice({ tone, icon, children }: { tone: 'info' | 'warn' | 'danger'; icon: React.ReactNode; children: React.ReactNode }) {
  const cls = tone === 'danger' ? 'border-danger/30 bg-danger-soft text-danger' : tone === 'warn' ? 'border-warn/30 bg-warn-soft text-warn' : 'border-line bg-soft text-fg'
  return (
    <div role={tone === 'danger' ? 'alert' : 'note'} className={`flex items-start gap-2.5 rounded-xl border px-3.5 py-3 text-sm ${cls}`}>
      <span className="mt-0.5 shrink-0" aria-hidden>{icon}</span>
      <div className="min-w-0 flex-1 break-words">{children}</div>
    </div>
  )
}

export default function CallPage() {
  const qc = useQueryClient()
  const status = useAgoraStatus()
  const { data: prefs } = usePrefs()
  const { selected } = useLanguage()
  const { state, start, end, setMuted } = useLiveCall()

  const languages = useMemo(() => callLanguages(status.data?.languages), [status.data?.languages])
  const [picked, setPicked] = useState<string | null>(null)
  const defaultLang = useMemo(() => pickCallLanguage(languages, [selected === AUTO_LANGUAGE ? null : selected, prefs?.primary_language]), [languages, selected, prefs?.primary_language])
  const language = picked && languages.some((l) => l.code === picked) ? picked : defaultLang

  const live = isCallLive(state.phase)
  const active = state.phase === 'active'
  const copy = statusCopy(state)
  const orb = orbStateFor(state)

  // Waveform reads the freshest Agora levels through refs so it never re-subscribes on every volume event.
  const levels = useRef({ local: 0, remote: 0 })
  levels.current = { local: state.muted ? 0 : state.local, remote: state.remote }
  const analyser = useMemo(() => createLevelAnalyser(() => Math.max(levels.current.local, levels.current.remote)), [])

  // One last transcript refresh just after the call (the final turn is saved a moment later).
  const conversationId = state.conversationId
  useEffect(() => {
    if (state.phase !== 'ended' || !conversationId) return
    const t = window.setTimeout(() => void qc.invalidateQueries({ queryKey: qk.callTranscript(conversationId) }), 900)
    return () => window.clearTimeout(t)
  }, [state.phase, conversationId, qc])

  const startCall = () => start(language, state.conversationId)
  const lowTime = active && state.remaining !== null && state.remaining <= 300

  /* ---------------------------------------------------------------- availability gates */
  let gate: React.ReactNode = null
  if (status.isLoading) {
    gate = (
      <div className="mt-6 space-y-4" aria-busy aria-label="Checking live call availability">
        <Skeleton className="mx-auto size-40 rounded-full" />
        <Skeleton className="mx-auto h-8 w-2/3" />
      </div>
    )
  } else if (status.isError) {
    gate = (
      <section className="card mt-6 p-5 text-center" role="alert">
        <div className="mx-auto mb-3 grid size-12 place-items-center rounded-2xl bg-warn-soft text-warn"><WifiOff className="size-6" aria-hidden /></div>
        <h2 className="text-lg font-semibold">We could not check live calls</h2>
        <p className="mx-auto mt-1.5 max-w-sm text-sm text-muted">{(status.error as { status?: number } | null)?.status === 404 ? 'This server does not have live calls yet.' : status.error instanceof Error ? status.error.message : 'The server did not answer.'} You can still use the text chat.</p>
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          <Button variant="secondary" onClick={() => void status.refetch()}>Try again</Button>
          <Link to="/chat" className="inline-flex h-12 items-center justify-center gap-2 rounded-2xl bg-accent px-5 text-[15px] font-semibold text-accent-fg">Open the text chat</Link>
        </div>
      </section>
    )
  } else if (status.data && (!status.data.configured || status.data.mode === 'unconfigured' || languages.length === 0)) {
    gate = (
      <section className="card mt-6 p-5 text-center" aria-labelledby="unconf-h">
        <div className="mx-auto mb-3 grid size-12 place-items-center rounded-2xl bg-accent-soft text-accent-text"><Phone className="size-6" aria-hidden /></div>
        <h2 id="unconf-h" className="text-lg font-semibold">Live calls are not set up yet</h2>
        <p className="mx-auto mt-1.5 max-w-sm text-sm text-muted">{status.data.note || 'Live calls need Agora and Murf keys in backend/.env.'}</p>
        <Link to="/chat" className="mt-4 inline-flex h-12 items-center justify-center gap-2 rounded-2xl bg-accent px-5 text-[15px] font-semibold text-accent-fg">
          <MessageSquareText className="size-4" aria-hidden /> Use the text chat
        </Link>
      </section>
    )
  }

  const chatOnly = status.data?.configured && status.data.mode === 'chat_only'

  return (
    <div className="page-glow flex min-h-full flex-col">
      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-4 pt-4 pb-6 md:px-6">
        <div className="flex items-center gap-2">
          <h1 className="text-lg font-semibold tracking-tight">Live call</h1>
          <div className="flex-1" />
          <Link to="/chat" className="inline-flex min-h-11 items-center gap-1.5 rounded-xl px-3 text-sm font-medium text-muted transition hover:bg-soft hover:text-fg">
            <MessageSquareText className="size-4" aria-hidden /> Text chat
          </Link>
        </div>

        {gate ?? (
          <>
            {chatOnly && (
              <div className="mt-3">
                <Notice tone="warn" icon={<Info className="size-4" />}>
                  This call can talk, but it cannot book appointments or look things up until the server has a public URL.
                  {status.data?.note && <span className="mt-1 block text-xs text-muted">{status.data.note}</span>}
                </Notice>
              </div>
            )}

            {/* language (only before a call) */}
            {(state.phase === 'idle' || state.phase === 'error' || state.phase === 'ended') && (
              <div className="mt-4" role="group" aria-labelledby="call-lang-h">
                <h2 id="call-lang-h" className="mb-2 text-sm font-semibold">Call language</h2>
                <div className="flex flex-wrap gap-2">
                  {languages.map((l) => (
                    <ToggleChip key={l.code} solid active={l.code === language} onClick={() => setPicked(l.code)}>
                      <span lang={l.code}>{l.native_name}</span>
                      {l.native_name !== l.name && <span className="text-xs opacity-70">{l.name}</span>}
                    </ToggleChip>
                  ))}
                </div>
              </div>
            )}

            {/* orb + status */}
            <div className="flex flex-col items-center pt-3">
              <VoiceOrb
                state={orb}
                listeningIcon={Mic}
                level={Math.min(1, state.local / 60)}
                onClick={() => (state.phase === 'idle' || state.phase === 'ended' || state.phase === 'error' ? startCall() : active ? setMuted(!state.muted) : undefined)}
                disabled={!(state.phase === 'idle' || state.phase === 'ended' || state.phase === 'error' || active)}
                label={active ? (state.muted ? 'Unmute microphone' : 'Mute microphone') : live ? 'Call in progress' : state.phase === 'idle' ? 'Start call' : 'Call again'}
              />
              <div className="mt-1 text-center" aria-live="polite" aria-atomic="true">
                <div className="text-xl font-semibold tracking-tight">{copy.title}</div>
                {copy.hint && <div className="mt-0.5 max-w-sm text-sm text-muted">{copy.hint}</div>}
              </div>
              {(active || state.phase === 'ending' || state.phase === 'ended') && state.startedAt !== null && (
                <div className="mt-2 font-mono text-lg tabular-nums text-muted" role="timer" aria-label={`Call time ${formatTimer(state.elapsed)}`}>
                  {formatTimer(state.elapsed)}
                </div>
              )}
              <Waveform className="mt-3 max-w-md" analyser={active ? analyser : null} active={active && orb !== 'idle'} />
            </div>

            {/* notices */}
            <div className="mt-3 space-y-2">
              {state.phase === 'error' && state.error && (
                <Notice tone="danger" icon={<TriangleAlert className="size-4" />}>
                  <div className="font-medium">{state.error.message}</div>
                </Notice>
              )}
              {state.notice && <Notice tone="warn" icon={<Info className="size-4" />}>{state.notice}</Notice>}
              {lowTime && <Notice tone="info" icon={<Info className="size-4" />}>This call will end automatically in {formatTimer(state.remaining ?? 0)}. You can call again right away.</Notice>}
            </div>

            {/* controls */}
            <div className="mt-4 flex flex-wrap items-center justify-center gap-3">
              {live ? (
                <>
                  {active && (
                    <Button size="lg" variant={state.muted ? 'soft' : 'secondary'} aria-pressed={state.muted} onClick={() => setMuted(!state.muted)} className="min-w-36">
                      {state.muted ? <MicOff className="size-5" aria-hidden /> : <Mic className="size-5" aria-hidden />}
                      {state.muted ? 'Unmute' : 'Mute'}
                    </Button>
                  )}
                  <Button size="lg" variant="danger" onClick={end} disabled={state.phase === 'ending'} className="min-w-36">
                    <PhoneOff className="size-5" aria-hidden /> {active ? 'End call' : 'Cancel'}
                  </Button>
                </>
              ) : (
                <Button size="lg" variant="primary" onClick={startCall} className="w-full max-w-xs">
                  <Phone className="size-5" aria-hidden />
                  {state.phase === 'ended' ? 'Call again' : state.phase === 'error' ? 'Try again' : 'Start call'}
                </Button>
              )}
              {state.phase === 'error' && state.error?.kind === 'not_configured' && (
                <Link to="/chat" className="inline-flex min-h-11 items-center text-sm font-medium text-accent-text hover:underline">Use the text chat</Link>
              )}
            </div>

            {/* transcript */}
            {state.conversationId && (
              <div className="mt-6">
                <CallTranscript conversationId={state.conversationId} live={live} />
              </div>
            )}
            {!state.conversationId && state.phase === 'idle' && (
              <p className="mx-auto mt-6 flex max-w-sm items-start gap-2 text-center text-sm text-muted">
                <AudioLines className="mt-0.5 size-4 shrink-0 text-accent-text" aria-hidden />
                <span>Speak naturally. Your assistant answers out loud and the conversation is saved so you can read it later.</span>
              </p>
            )}
          </>
        )}

        <div className="flex-1" />
        <p className="mt-8 text-center text-xs text-muted">Voice: Agora Conversational AI · Speech: Murf Falcon</p>
      </div>
    </div>
  )
}
