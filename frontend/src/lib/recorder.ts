import { SilenceDetector, type StopReason } from './vad'
import { concatFloat32, downsample, encodeWav, rms, TARGET_SAMPLE_RATE } from './wav'

/** Inline AudioWorklet: copies each 128-sample mic block to the main thread. */
const WORKLET_SOURCE = `
class PcmCapture extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0]
    if (ch && ch.length) this.port.postMessage(ch.slice(0))
    return true
  }
}
registerProcessor('pcm-capture', PcmCapture)
`

/** Default cap if the server did not say otherwise (the backend rejects clips over 60 s). */
export const DEFAULT_MAX_RECORD_MS = 55_000

/**
 * Recording cap for a server limit: stop 2 s early so the clip (plus encoding overhead) is always accepted,
 * but never below 5 s and never above the default.
 */
export function maxRecordMs(serverLimitSeconds: number | undefined): number {
  if (!serverLimitSeconds || !Number.isFinite(serverLimitSeconds)) return DEFAULT_MAX_RECORD_MS
  return Math.round(Math.max(5_000, Math.min(DEFAULT_MAX_RECORD_MS, (serverLimitSeconds - 2) * 1000)))
}

export type MicErrorKind = 'denied' | 'no-device' | 'unsupported' | 'failed'

export class MicError extends Error {
  kind: MicErrorKind
  constructor(kind: MicErrorKind, message: string) {
    super(message)
    this.kind = kind
  }
}

export interface RecordingResult {
  blob: Blob
  durationMs: number
  hadSpeech: boolean
  reason: StopReason | 'manual' | 'max'
}

export interface RecorderOptions {
  silenceMs: number
  /** Hard recording cap in ms (see maxRecordMs). */
  maxMs?: number
  onLevel?: (level: number) => void
  /** Called once when the recorder decides to stop by itself (silence / max length / nothing said). */
  onAutoStop?: (reason: Exclude<RecordingResult['reason'], 'manual'>) => void
}

function micError(err: unknown): MicError {
  const name = (err as DOMException | undefined)?.name
  if (name === 'NotAllowedError' || name === 'SecurityError') return new MicError('denied', 'Microphone access was blocked. Allow the microphone in your browser, or type your message instead.')
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return new MicError('no-device', 'No microphone was found. Connect one, or type your message instead.')
  return new MicError('failed', 'Could not start the microphone. You can type your message instead.')
}

export function micSupported(): boolean {
  return typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof AudioContext !== 'undefined' && typeof AudioWorkletNode !== 'undefined'
}

/** Records the mic to 16 kHz mono WAV, with a live level meter, an analyser for waveforms, and silence auto-stop. */
export class VoiceRecorder {
  private stream: MediaStream | null = null
  private ctx: AudioContext | null = null
  private node: AudioWorkletNode | null = null
  private source: MediaStreamAudioSourceNode | null = null
  private sink: GainNode | null = null
  private chunks: Float32Array[] = []
  private vad: SilenceDetector
  private frameSamples = 0
  private frameEnergy = 0
  private startedAt = 0
  private finished = false
  analyser: AnalyserNode | null = null

  constructor(private readonly opts: RecorderOptions) {
    this.vad = new SilenceDetector({ silenceMs: opts.silenceMs })
  }

  async start(): Promise<void> {
    if (!micSupported()) throw new MicError('unsupported', 'This browser cannot record audio. Please type your message instead.')
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
    } catch (err) {
      throw micError(err)
    }
    try {
      this.ctx = new AudioContext({ latencyHint: 'interactive' })
      const url = URL.createObjectURL(new Blob([WORKLET_SOURCE], { type: 'application/javascript' }))
      try {
        await this.ctx.audioWorklet.addModule(url)
      } finally {
        URL.revokeObjectURL(url)
      }
      if (this.ctx.state === 'suspended') await this.ctx.resume()
      this.source = this.ctx.createMediaStreamSource(this.stream)
      this.analyser = this.ctx.createAnalyser()
      this.analyser.fftSize = 256
      this.analyser.smoothingTimeConstant = 0.7
      this.node = new AudioWorkletNode(this.ctx, 'pcm-capture')
      this.node.port.onmessage = (e: MessageEvent<Float32Array>) => this.onBlock(e.data)
      this.source.connect(this.analyser)
      this.source.connect(this.node)
      // Browsers only "pull" nodes that reach the destination, so route the worklet through a muted sink.
      this.sink = this.ctx.createGain()
      this.sink.gain.value = 0
      this.node.connect(this.sink)
      this.sink.connect(this.ctx.destination)
      this.startedAt = performance.now()
    } catch (err) {
      this.release()
      throw err instanceof MicError ? err : new MicError('failed', 'Could not start the microphone. You can type your message instead.')
    }
  }

  private onBlock(block: Float32Array) {
    if (this.finished || !this.ctx) return
    this.chunks.push(block)
    // Evaluate speech in ~50 ms frames.
    for (let i = 0; i < block.length; i++) this.frameEnergy += (block[i] as number) * (block[i] as number)
    this.frameSamples += block.length
    const frameMs = (this.frameSamples / this.ctx.sampleRate) * 1000
    if (frameMs < 50) return
    const frameRms = Math.sqrt(this.frameEnergy / this.frameSamples)
    this.frameSamples = 0
    this.frameEnergy = 0
    this.opts.onLevel?.(Math.min(1, frameRms * 7))

    const result = this.vad.push(frameRms, frameMs)
    if (performance.now() - this.startedAt >= (this.opts.maxMs ?? DEFAULT_MAX_RECORD_MS)) this.opts.onAutoStop?.('max')
    else if (result.stopReason) this.opts.onAutoStop?.(result.stopReason)
  }

  /** Stop and return the recording as a WAV blob. Safe to call once. */
  async stop(reason: RecordingResult['reason'] = 'manual'): Promise<RecordingResult> {
    this.finished = true
    const rate = this.ctx?.sampleRate ?? TARGET_SAMPLE_RATE
    const raw = concatFloat32(this.chunks)
    const durationMs = Math.round((raw.length / rate) * 1000)
    const { data, rate: outRate } = downsample(raw, rate, TARGET_SAMPLE_RATE)
    const hadSpeech = this.vad.speechDetected || rms(data) > 0.03
    const blob = new Blob([encodeWav(data, outRate)], { type: 'audio/wav' })
    this.release()
    return { blob, durationMs, hadSpeech, reason }
  }

  cancel() {
    this.finished = true
    this.release()
  }

  private release() {
    this.opts.onLevel?.(0)
    if (this.node) this.node.port.onmessage = null
    this.source?.disconnect()
    this.node?.disconnect()
    this.sink?.disconnect()
    this.stream?.getTracks().forEach((t) => t.stop())
    void this.ctx?.close().catch(() => undefined)
    this.stream = this.ctx = this.node = this.source = this.sink = this.analyser = null
    this.chunks = []
  }
}
