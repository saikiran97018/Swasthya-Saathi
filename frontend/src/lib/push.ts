/** Phone / browser notifications (Web Push) for reminders: permission, service worker, subscription. */

export type PushState = 'unsupported' | 'blocked' | 'off' | 'on'

export function pushSupported(): boolean {
  return typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

/** Browsers want the server's public key as bytes, not base64url text. */
export function urlBase64ToUint8Array(value: string): Uint8Array<ArrayBuffer> {
  const padded = value + '='.repeat((4 - (value.length % 4)) % 4)
  const raw = atob(padded.replace(/-/g, '+').replace(/_/g, '/'))
  const out = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i)
  return out
}

async function registration(): Promise<ServiceWorkerRegistration> {
  const existing = await navigator.serviceWorker.getRegistration('/')
  return existing ?? navigator.serviceWorker.register('/sw.js', { scope: '/' })
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null
  try {
    const reg = await navigator.serviceWorker.getRegistration('/')
    return (await reg?.pushManager.getSubscription()) ?? null
  } catch {
    return null
  }
}

export async function pushState(): Promise<PushState> {
  if (!pushSupported()) return 'unsupported'
  if (Notification.permission === 'denied') return 'blocked'
  return Notification.permission === 'granted' && (await currentSubscription()) ? 'on' : 'off'
}

export class PushError extends Error {
  constructor(public reason: 'unsupported' | 'blocked' | 'failed', message: string) {
    super(message)
    this.name = 'PushError'
  }
}

/** Ask permission (a browser prompt), register the service worker and subscribe this device. */
export async function enablePush(publicKey: string): Promise<PushSubscription> {
  if (!pushSupported()) throw new PushError('unsupported', 'This browser cannot show notifications. On an iPhone, add Saathi to your Home Screen first.')
  const permission = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission()
  if (permission !== 'granted') throw new PushError('blocked', 'Notifications are blocked for this site. Allow them in your browser settings, then try again.')
  try {
    const reg = await registration()
    await navigator.serviceWorker.ready
    return (await reg.pushManager.getSubscription()) ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(publicKey) }))
  } catch {
    throw new PushError('failed', 'Could not turn on notifications on this device.')
  }
}

/** Unsubscribe this device; returns the endpoint so the server can forget it. */
export async function disablePush(): Promise<string | null> {
  const sub = await currentSubscription()
  if (!sub) return null
  const endpoint = sub.endpoint
  await sub.unsubscribe().catch(() => false)
  return endpoint
}
