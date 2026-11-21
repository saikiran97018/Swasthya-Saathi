import { describe, expect, it } from 'vitest'
import type { ToolExecution } from '@/api/types'
import { actionsToRun, createClaimer, extractUiAction, isFresh, safePath } from './uiActions'

function run(over: Partial<ToolExecution> = {}): ToolExecution {
  return {
    id: 'e1', execution_id: 'x', conversation_id: 'c', assistant_message_id: null, tool_name: 'control_app', arguments: {},
    result: { ui_action: { type: 'open_page', page: 'sos', path: '/sos', label: 'SOS' } }, summary: null, explanation: null, status: 'success',
    requires_confirmation: false, duration_ms: 1, error: null, created_at: new Date().toISOString(), ...over,
  }
}

describe('safePath', () => {
  it('accepts the app pages', () => {
    for (const p of ['/', '/chat', '/find-care', '/appointments', '/family', '/sos', '/history', '/activity', '/settings', '/settings/language', '/call']) expect(safePath(p)).toBe(p)
  })
  it('accepts a city only on the doctors page and encodes it', () => {
    expect(safePath('/find-care?city=Guntur')).toBe('/find-care?city=Guntur')
    expect(safePath('/find-care?city=New+Delhi')).toBe('/find-care?city=New%20Delhi')
    expect(safePath('/family?city=Guntur')).toBeNull()
  })
  it('refuses everything else', () => {
    for (const p of ['https://evil.example.com', '//evil.example.com', '/\\evil', '/admin', '/voice', '/sos/../x', '/find-care?city=a&x=1', '/find-care?x=1', '/find-care?city=', '/find-care?city=<script>', '/find-care?city=a?b', '', null, 42, undefined]) {
      expect(safePath(p as never)).toBeNull()
    }
    expect(safePath('/find-care?city=' + 'x'.repeat(81))).toBeNull()
  })
})

describe('extractUiAction', () => {
  it('reads an open_page action', () => {
    expect(extractUiAction(run())).toEqual({ type: 'open_page', path: '/sos', label: 'SOS' })
  })
  it('reads a theme action and rejects odd themes', () => {
    expect(extractUiAction(run({ result: { ui_action: { type: 'set_theme', theme: 'dark' } } }))).toEqual({ type: 'set_theme', theme: 'dark' })
    expect(extractUiAction(run({ result: { ui_action: { type: 'set_theme', theme: 'neon' } } }))).toBeNull()
  })
  it('ignores other tools, failed runs and malformed results', () => {
    expect(extractUiAction(run({ tool_name: 'book_appointment' }))).toBeNull()
    expect(extractUiAction(run({ status: 'error' }))).toBeNull()
    expect(extractUiAction(run({ status: 'awaiting_confirmation' }))).toBeNull()
    expect(extractUiAction(run({ result: null }))).toBeNull()
    expect(extractUiAction(run({ result: { ui_action: 'open /sos' } }))).toBeNull()
    expect(extractUiAction(run({ result: { ui_action: { type: 'open_page', path: 'https://evil.example.com' } } }))).toBeNull()
    expect(extractUiAction(run({ result: { ui_action: { type: 'delete_account' } } }))).toBeNull()
  })
})

describe('freshness and once-only', () => {
  it('only counts runs from about now', () => {
    const now = Date.now()
    expect(isFresh(new Date(now).toISOString(), now)).toBe(true)
    expect(isFresh(new Date(now - 10_000).toISOString(), now)).toBe(true)
    expect(isFresh(new Date(now - 3_600_000).toISOString(), now)).toBe(false)
    expect(isFresh('not a date', now)).toBe(false)
  })
  it('carries each run out once, in order, and skips old history', () => {
    const now = Date.now()
    const claim = createClaimer()
    const old = run({ id: 'old', created_at: new Date(now - 86_400_000).toISOString() })
    const a = run({ id: 'a' })
    const b = run({ id: 'b', result: { ui_action: { type: 'set_theme', theme: 'light' } } })
    expect(actionsToRun([old, a, b], now, claim)).toEqual([{ type: 'open_page', path: '/sos', label: 'SOS' }, { type: 'set_theme', theme: 'light' }])
    expect(actionsToRun([old, a, b], now, claim)).toEqual([]) // seen again (re-render, next poll): nothing happens twice
  })
})
