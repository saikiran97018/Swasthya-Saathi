/**
 * Tiny voice-activity detector used to auto-stop recording.
 *
 * It calibrates a noise floor from the first few hundred milliseconds, then decides frame by frame
 * whether the user is speaking. Recording should stop once speech has been heard and has been
 * followed by `silenceMs` of quiet, or when nothing at all was said for `noSpeechMs`.
 */
export interface VadOptions {
  silenceMs: number
  calibrateMs?: number
  minSpeechMs?: number
  minThreshold?: number
  noSpeechMs?: number
}

export type StopReason = 'silence' | 'no-speech' | null

export interface VadResult {
  speaking: boolean
  speechDetected: boolean
  stopReason: StopReason
}

export class SilenceDetector {
  private readonly o: Required<VadOptions>
  private elapsed = 0
  private noiseSum = 0
  private noiseMs = 0
  private threshold: number
  private speechMs = 0
  private silenceRun = 0
  private heard = false

  constructor(options: VadOptions) {
    this.o = { calibrateMs: 300, minSpeechMs: 150, minThreshold: 0.02, noSpeechMs: 8000, ...options }
    this.threshold = this.o.minThreshold
  }

  get speechDetected() {
    return this.heard
  }

  push(frameRms: number, frameMs: number): VadResult {
    this.elapsed += frameMs

    if (this.noiseMs < this.o.calibrateMs) {
      // Still measuring background noise. A very loud frame is clearly speech, not noise.
      if (frameRms < this.o.minThreshold * 4) {
        this.noiseSum += frameRms * frameMs
        this.noiseMs += frameMs
        if (this.noiseMs >= this.o.calibrateMs) this.threshold = Math.max(this.o.minThreshold, (this.noiseSum / this.noiseMs) * 3)
        return { speaking: false, speechDetected: this.heard, stopReason: this.noSpeechStop() }
      }
    }

    const speaking = frameRms > this.threshold
    if (speaking) {
      this.speechMs += frameMs
      this.silenceRun = 0
      if (this.speechMs >= this.o.minSpeechMs) this.heard = true
    } else if (this.heard) {
      this.silenceRun += frameMs
    }

    let stopReason: StopReason = null
    if (this.heard && this.silenceRun >= this.o.silenceMs) stopReason = 'silence'
    else stopReason = this.noSpeechStop()
    return { speaking, speechDetected: this.heard, stopReason }
  }

  private noSpeechStop(): StopReason {
    return !this.heard && this.elapsed >= this.o.noSpeechMs ? 'no-speech' : null
  }
}
