/**
 * Plays synthesized speech through ONE persistent <audio> element so we can stop, pause and
 * visualise it. Audio is queued: each item is a promise for a WAV blob, so synthesis requests can be
 * fired as soon as a sentence is ready while playback proceeds in order.
 */

export type PlayerStatus = 'idle' | 'loading' | 'playing' | 'paused'

export interface PlayerSnapshot {
  status: PlayerStatus
  /** Message whose audio is currently queued or playing (null when idle). */
  messageId: string | null
  error: string | null
}

interface QueueItem {
  messageId: string
  blob: Promise<Blob>
}

type Listener = () => void

export class SpeechPlayer {
  private audio: HTMLAudioElement | null = null
  private queue: QueueItem[] = []
  private running = false
  private generation = 0
  private snapshot: PlayerSnapshot = { status: 'idle', messageId: null, error: null }
  private listeners = new Set<Listener>()
  private ctx: AudioContext | null = null
  analyser: AnalyserNode | null = null

  subscribe = (l: Listener) => {
    this.listeners.add(l)
    return () => this.listeners.delete(l)
  }

  getSnapshot = (): PlayerSnapshot => this.snapshot

  private set(patch: Partial<PlayerSnapshot>) {
    this.snapshot = { ...this.snapshot, ...patch }
    this.listeners.forEach((l) => l())
  }

  private ensureAudio(): HTMLAudioElement {
    if (!this.audio) {
      this.audio = new Audio()
      this.audio.preload = 'auto'
    }
    return this.audio
  }

  /** Create the analyser lazily (needs a user gesture in some browsers; failure just disables the visual). */
  private ensureAnalyser() {
    if (this.analyser || typeof AudioContext === 'undefined') return
    try {
      const audio = this.ensureAudio()
      this.ctx = new AudioContext()
      const src = this.ctx.createMediaElementSource(audio)
      this.analyser = this.ctx.createAnalyser()
      this.analyser.fftSize = 128
      this.analyser.smoothingTimeConstant = 0.75
      src.connect(this.analyser)
      this.analyser.connect(this.ctx.destination)
    } catch {
      this.analyser = null
    }
  }

  enqueue(messageId: string, blob: Promise<Blob>) {
    // Avoid unhandled-rejection noise: errors are reported through the snapshot when the item is reached.
    blob.catch(() => undefined)
    this.queue.push({ messageId, blob })
    this.set({ messageId, status: this.snapshot.status === 'idle' ? 'loading' : this.snapshot.status, error: null })
    void this.run()
  }

  private async run() {
    if (this.running) return
    this.running = true
    const gen = this.generation
    try {
      while (this.queue.length && gen === this.generation) {
        const item = this.queue.shift() as QueueItem
        this.set({ messageId: item.messageId, status: 'loading' })
        let blob: Blob
        try {
          blob = await item.blob
        } catch (err) {
          if (gen !== this.generation) break
          this.set({ error: err instanceof Error ? err.message : 'Could not generate speech' })
          continue
        }
        if (gen !== this.generation) break
        await this.playBlob(blob, gen)
      }
    } finally {
      // Only the current loop may reset state: a loop that stop() superseded must not touch the new one.
      if (gen === this.generation) {
        this.running = false
        this.set({ status: 'idle', messageId: null })
      }
    }
  }

  private async playBlob(blob: Blob, gen: number) {
    const audio = this.ensureAudio()
    this.ensureAnalyser()
    if (this.ctx?.state === 'suspended') await this.ctx.resume().catch(() => undefined)
    const url = URL.createObjectURL(blob)
    try {
      await new Promise<void>((resolve) => {
        const done = () => {
          audio.removeEventListener('ended', done)
          audio.removeEventListener('error', fail)
          resolve()
        }
        const fail = () => {
          this.set({ error: 'Could not play the audio' })
          done()
        }
        audio.addEventListener('ended', done)
        audio.addEventListener('error', fail)
        audio.src = url
        audio.onpause = () => {
          if (gen !== this.generation) done() // stop() was called
        }
        audio.play().then(() => {
          if (gen === this.generation) this.set({ status: 'playing' })
        }, (err: unknown) => {
          this.set({ error: (err as Error)?.name === 'NotAllowedError' ? 'Tap the speaker button to allow audio playback' : 'Could not play the audio' })
          done()
        })
      })
    } finally {
      audio.onpause = null
      URL.revokeObjectURL(url)
    }
  }

  pause() {
    if (this.snapshot.status === 'playing') {
      // pause without invalidating the generation: onpause only ends playback when generation changed
      this.audio?.pause()
      this.set({ status: 'paused' })
    }
  }

  resume() {
    if (this.snapshot.status === 'paused') {
      void this.audio?.play()
      this.set({ status: 'playing' })
    }
  }

  /** Stop immediately and drop everything queued. */
  stop() {
    this.generation += 1
    this.queue = []
    if (this.audio) {
      this.audio.pause()
      this.audio.removeAttribute('src')
      this.audio.load()
    }
    this.running = false
    this.set({ status: 'idle', messageId: null })
  }

  get isBusy() {
    return this.snapshot.status !== 'idle'
  }
}

export const speechPlayer = new SpeechPlayer()
