import { describe, expect, it } from 'vitest'
import { SilenceDetector } from './vad'

/** Feed N frames of the same level (each `frameMs` long) and return the last result. */
function feed(v: SilenceDetector, level: number, frames: number, frameMs = 50) {
  let last = v.push(level, frameMs)
  for (let i = 1; i < frames; i++) last = v.push(level, frameMs)
  return last
}

describe('SilenceDetector', () => {
  it('stops after speech followed by the configured silence', () => {
    const v = new SilenceDetector({ silenceMs: 1000 })
    feed(v, 0.002, 8) // calibrate on quiet room noise (400 ms)
    expect(feed(v, 0.2, 10).speechDetected).toBe(true) // 500 ms of speech
    expect(feed(v, 0.002, 19).stopReason).toBeNull() // 950 ms quiet: not yet
    expect(feed(v, 0.002, 1).stopReason).toBe('silence') // 1000 ms
  })

  it('does not stop during a pause shorter than the timeout', () => {
    const v = new SilenceDetector({ silenceMs: 1500 })
    feed(v, 0.002, 8)
    feed(v, 0.2, 6)
    feed(v, 0.002, 20) // 1 s pause
    expect(feed(v, 0.2, 4).stopReason).toBeNull() // user resumes: silence counter resets
    expect(feed(v, 0.002, 29).stopReason).toBeNull()
  })

  it('ignores very short noises (clicks) as speech', () => {
    const v = new SilenceDetector({ silenceMs: 500 })
    feed(v, 0.002, 8)
    expect(feed(v, 0.3, 1).speechDetected).toBe(false) // 50 ms < minSpeechMs
  })

  it('gives up if nothing is said at all', () => {
    const v = new SilenceDetector({ silenceMs: 1000, noSpeechMs: 2000 })
    expect(feed(v, 0.002, 39).stopReason).toBeNull()
    expect(feed(v, 0.002, 1).stopReason).toBe('no-speech')
  })

  it('adapts to a noisy room: steady background noise is not speech', () => {
    const v = new SilenceDetector({ silenceMs: 1000 })
    feed(v, 0.012, 8) // noisy but constant (threshold becomes ~0.036)
    expect(feed(v, 0.012, 10).speechDetected).toBe(false)
    expect(feed(v, 0.2, 5).speechDetected).toBe(true)
  })

  it('treats a loud first frame as speech, not as noise to calibrate on', () => {
    const v = new SilenceDetector({ silenceMs: 500 })
    feed(v, 0.3, 4)
    expect(v.speechDetected).toBe(true)
  })
})
