/** Audio helpers: downsample float PCM and encode it as a 16-bit mono WAV the backend accepts. */

export const TARGET_SAMPLE_RATE = 16000

/**
 * Downsample by averaging the input samples that fall into each output sample (a box filter, which
 * also acts as a cheap anti-aliasing low-pass). Never upsamples: if the input is already at or below
 * the target rate it is returned unchanged together with its real rate.
 */
export function downsample(input: Float32Array, inputRate: number, targetRate: number = TARGET_SAMPLE_RATE): { data: Float32Array; rate: number } {
  if (inputRate <= targetRate) return { data: input, rate: inputRate }
  const ratio = inputRate / targetRate
  const outLength = Math.floor(input.length / ratio)
  const out = new Float32Array(outLength)
  for (let i = 0; i < outLength; i++) {
    const start = Math.floor(i * ratio)
    const end = Math.min(input.length, Math.floor((i + 1) * ratio))
    let sum = 0
    for (let j = start; j < end; j++) sum += input[j] as number
    out[i] = end > start ? sum / (end - start) : 0
  }
  return { data: out, rate: targetRate }
}

/** Convert float samples in [-1, 1] to signed 16-bit, clipping anything outside that range. */
export function floatTo16BitPCM(samples: Float32Array): Int16Array {
  const out = new Int16Array(samples.length)
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i] as number))
    out[i] = s < 0 ? Math.round(s * 0x8000) : Math.round(s * 0x7fff)
  }
  return out
}

function writeString(view: DataView, offset: number, text: string) {
  for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i))
}

/** Encode mono float samples as a canonical 44-byte-header PCM16 WAV. */
export function encodeWav(samples: Float32Array, sampleRate: number): ArrayBuffer {
  const pcm = floatTo16BitPCM(samples)
  const dataBytes = pcm.length * 2
  const buffer = new ArrayBuffer(44 + dataBytes)
  const view = new DataView(buffer)

  writeString(view, 0, 'RIFF')
  view.setUint32(4, 36 + dataBytes, true)
  writeString(view, 8, 'WAVE')
  writeString(view, 12, 'fmt ')
  view.setUint32(16, 16, true) // fmt chunk size
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // mono
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true) // byte rate
  view.setUint16(32, 2, true) // block align
  view.setUint16(34, 16, true) // bits per sample
  writeString(view, 36, 'data')
  view.setUint32(40, dataBytes, true)
  for (let i = 0; i < pcm.length; i++) view.setInt16(44 + i * 2, pcm[i] as number, true)
  return buffer
}

/** Join recorded chunks into one contiguous Float32Array. */
export function concatFloat32(chunks: Float32Array[]): Float32Array {
  const total = chunks.reduce((n, c) => n + c.length, 0)
  const out = new Float32Array(total)
  let offset = 0
  for (const c of chunks) {
    out.set(c, offset)
    offset += c.length
  }
  return out
}

export function rms(samples: Float32Array): number {
  if (samples.length === 0) return 0
  let sum = 0
  for (let i = 0; i < samples.length; i++) {
    const v = samples[i] as number
    sum += v * v
  }
  return Math.sqrt(sum / samples.length)
}
