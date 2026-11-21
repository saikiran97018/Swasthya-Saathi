import { describe, expect, it } from 'vitest'
import { DEFAULT_MAX_RECORD_MS, maxRecordMs } from './recorder'

describe('maxRecordMs (follow the server recording limit)', () => {
  it('stops 2 seconds before the server limit', () => {
    expect(maxRecordMs(30)).toBe(28_000)
    expect(maxRecordMs(20)).toBe(18_000)
  })

  it('never exceeds the default cap, even for a generous server limit', () => {
    expect(maxRecordMs(60)).toBe(DEFAULT_MAX_RECORD_MS)
    expect(maxRecordMs(300)).toBe(DEFAULT_MAX_RECORD_MS)
  })

  it('never goes below 5 seconds', () => {
    expect(maxRecordMs(4)).toBe(5_000)
    expect(maxRecordMs(1)).toBe(5_000)
  })

  it('falls back to the default when the server did not say', () => {
    expect(maxRecordMs(undefined)).toBe(DEFAULT_MAX_RECORD_MS)
    expect(maxRecordMs(0)).toBe(DEFAULT_MAX_RECORD_MS)
    expect(maxRecordMs(Number.NaN)).toBe(DEFAULT_MAX_RECORD_MS)
  })
})
