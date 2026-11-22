import { afterEach, describe, expect, it, vi } from 'vitest'
import { disablePush, enablePush, PushError, pushState, pushSupported, urlBase64ToUint8Array } from './push'

afterEach(() => vi.unstubAllGlobals())

describe('urlBase64ToUint8Array', () => {
  it('decodes base64url without padding', () => {
    expect(Array.from(urlBase64ToUint8Array('AQID'))).toEqual([1, 2, 3])
    expect(Array.from(urlBase64ToUint8Array('-_8'))).toEqual([251, 255]) // url-safe alphabet, missing padding
  })
  it('decodes a 65-byte P-256 key to 65 bytes', () => {
    const key = btoa(String.fromCharCode(...Array.from({ length: 65 }, (_, i) => (i === 0 ? 4 : i)))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
    const out = urlBase64ToUint8Array(key)
    expect(out.length).toBe(65)
    expect(out[0]).toBe(4)
  })
})

describe('without browser support', () => {
  it('reports unsupported and refuses to enable', async () => {
    expect(pushSupported()).toBe(false) // jsdom has no service worker or PushManager
    expect(await pushState()).toBe('unsupported')
    await expect(enablePush('AAAA')).rejects.toMatchObject({ name: 'PushError', reason: 'unsupported' })
    expect(await disablePush()).toBeNull()
  })
})

describe('with browser support', () => {
  function fakeBrowser(permission: NotificationPermission, subscribed: boolean) {
    const sub = { endpoint: 'https://push.test/abc', unsubscribe: vi.fn().mockResolvedValue(true) }
    let current: typeof sub | null = subscribed ? sub : null
    const reg = {
      pushManager: {
        getSubscription: vi.fn(async () => current),
        subscribe: vi.fn(async (_options: { userVisibleOnly: boolean; applicationServerKey: Uint8Array }) => (current = sub)),
      },
    }
    vi.stubGlobal('PushManager', function PushManager() {})
    vi.stubGlobal('Notification', { permission, requestPermission: vi.fn(async () => permission) })
    vi.stubGlobal('navigator', { serviceWorker: { getRegistration: vi.fn(async () => reg), register: vi.fn(async () => reg), ready: Promise.resolve(reg) } })
    return { sub, reg }
  }

  it('is on only when permission is granted and a subscription exists', async () => {
    fakeBrowser('granted', true)
    expect(await pushState()).toBe('on')
    fakeBrowser('granted', false)
    expect(await pushState()).toBe('off')
    fakeBrowser('default', false)
    expect(await pushState()).toBe('off')
  })

  it('reports blocked when the person said no', async () => {
    fakeBrowser('denied', false)
    expect(await pushState()).toBe('blocked')
    await expect(enablePush('AAAA')).rejects.toBeInstanceOf(PushError)
  })

  it('subscribes with userVisibleOnly and the server key', async () => {
    const { reg, sub } = fakeBrowser('granted', false)
    expect(await enablePush('AQID')).toBe(sub)
    const opts = reg.pushManager.subscribe.mock.calls[0]?.[0]
    expect(opts?.userVisibleOnly).toBe(true)
    expect(Array.from(opts?.applicationServerKey ?? [])).toEqual([1, 2, 3])
  })

  it('unsubscribes and returns the endpoint for the server to forget', async () => {
    const { sub } = fakeBrowser('granted', true)
    expect(await disablePush()).toBe('https://push.test/abc')
    expect(sub.unsubscribe).toHaveBeenCalled()
  })
})
