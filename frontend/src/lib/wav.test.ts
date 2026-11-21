import { describe, expect, it } from 'vitest'
import { concatFloat32, downsample, encodeWav, floatTo16BitPCM, rms } from './wav'

const ascii = (view: DataView, offset: number, len: number) => String.fromCharCode(...Array.from({ length: len }, (_, i) => view.getUint8(offset + i)))

describe('encodeWav', () => {
  const samples = new Float32Array([0, 0.5, -0.5, 1, -1])
  const buf = encodeWav(samples, 16000)
  const view = new DataView(buf)

  it('writes a canonical PCM16 mono header', () => {
    expect(ascii(view, 0, 4)).toBe('RIFF')
    expect(ascii(view, 8, 4)).toBe('WAVE')
    expect(ascii(view, 12, 4)).toBe('fmt ')
    expect(view.getUint32(16, true)).toBe(16)
    expect(view.getUint16(20, true)).toBe(1) // PCM
    expect(view.getUint16(22, true)).toBe(1) // mono
    expect(view.getUint32(24, true)).toBe(16000)
    expect(view.getUint32(28, true)).toBe(32000) // byte rate
    expect(view.getUint16(32, true)).toBe(2) // block align
    expect(view.getUint16(34, true)).toBe(16)
    expect(ascii(view, 36, 4)).toBe('data')
  })

  it('has the right sizes and sample count', () => {
    expect(buf.byteLength).toBe(44 + samples.length * 2)
    expect(view.getUint32(40, true)).toBe(samples.length * 2)
    expect(view.getUint32(4, true)).toBe(36 + samples.length * 2)
  })

  it('stores little-endian samples', () => {
    expect(view.getInt16(44, true)).toBe(0)
    expect(view.getInt16(46, true)).toBe(16384) // 0.5
    expect(view.getInt16(48, true)).toBe(-16384)
  })

  it('records the sample rate it was given', () => {
    expect(new DataView(encodeWav(new Float32Array(4), 8000)).getUint32(24, true)).toBe(8000)
  })
})

describe('floatTo16BitPCM', () => {
  it('clips out-of-range samples instead of wrapping', () => {
    const pcm = floatTo16BitPCM(new Float32Array([2, -2, 1, -1, 0.99999]))
    expect(Array.from(pcm)).toEqual([32767, -32768, 32767, -32768, 32767])
  })
})

describe('downsample', () => {
  it('reduces 48 kHz to 16 kHz with a third of the samples', () => {
    const input = new Float32Array(4800).fill(0.25)
    const { data, rate } = downsample(input, 48000, 16000)
    expect(rate).toBe(16000)
    expect(data.length).toBe(1600)
    expect(data[10]).toBeCloseTo(0.25, 6) // a constant signal is preserved
  })

  it('averages neighbouring samples (anti-aliasing)', () => {
    const { data } = downsample(new Float32Array([1, -1, 1, -1]), 32000, 16000)
    expect(Array.from(data)).toEqual([0, 0])
  })

  it('handles non-integer ratios (44.1 kHz)', () => {
    const { data } = downsample(new Float32Array(44100).fill(0.5), 44100, 16000)
    expect(Math.abs(data.length - 16000)).toBeLessThanOrEqual(1)
    expect(data.every((v) => Math.abs(v - 0.5) < 1e-6)).toBe(true)
  })

  it('never upsamples; it returns the input with its real rate', () => {
    const input = new Float32Array(10)
    const out = downsample(input, 8000, 16000)
    expect(out.data).toBe(input)
    expect(out.rate).toBe(8000)
  })
})

describe('helpers', () => {
  it('concatenates chunks in order', () => {
    expect(Array.from(concatFloat32([new Float32Array([1, 2]), new Float32Array([3])]))).toEqual([1, 2, 3])
    expect(concatFloat32([]).length).toBe(0)
  })

  it('computes rms', () => {
    expect(rms(new Float32Array([]))).toBe(0)
    expect(rms(new Float32Array([0.5, -0.5, 0.5, -0.5]))).toBeCloseTo(0.5)
  })
})
