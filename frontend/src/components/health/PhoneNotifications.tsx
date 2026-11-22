import { useCallback, useEffect, useState } from 'react'
import { Bell } from 'lucide-react'
import { api } from '@/api/endpoints'
import { Button, Toggle } from '@/components/ui/primitives'
import { useToast } from '@/components/ui/Toast'
import { disablePush, enablePush, PushError, pushState, type PushState } from '@/lib/push'

/** Settings switch: show reminders as notifications on this phone or browser, even when the app is closed. */
export function PhoneNotifications() {
  const toast = useToast()
  const [state, setState] = useState<PushState | 'loading'>('loading')
  const [serverOff, setServerOff] = useState(false)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(() => void pushState().then(setState), [])
  useEffect(() => {
    refresh()
    api.pushConfig().then((c) => setServerOff(!c.available)).catch(() => undefined)
  }, [refresh])

  const turnOn = async () => {
    setBusy(true)
    try {
      const cfg = await api.pushConfig()
      if (!cfg.available) {
        setServerOff(true)
        return
      }
      const sub = await enablePush(cfg.public_key)
      const json = sub.toJSON() as { endpoint?: string; keys?: { p256dh?: string; auth?: string } }
      if (!json.endpoint || !json.keys?.p256dh || !json.keys.auth) throw new PushError('failed', 'Could not turn on notifications on this device.')
      await api.pushSubscribe({ endpoint: json.endpoint, keys: { p256dh: json.keys.p256dh, auth: json.keys.auth } })
      toast.success('Notifications are on for this device')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not turn on notifications')
    } finally {
      setBusy(false)
      refresh()
    }
  }

  const turnOff = async () => {
    setBusy(true)
    try {
      const endpoint = await disablePush()
      if (endpoint) await api.pushUnsubscribe(endpoint)
      toast.success('Notifications are off for this device')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not turn off notifications')
    } finally {
      setBusy(false)
      refresh()
    }
  }

  const sendTest = async () => {
    setBusy(true)
    try {
      const { sent } = await api.pushTest()
      if (sent) toast.success('Test sent. It should appear in a moment.')
      else toast.error('Nothing was sent. Turn notifications off and on again.')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not send the test')
    } finally {
      setBusy(false)
    }
  }

  const description =
    serverOff ? 'Not available: this server has notifications turned off. Reminders still appear in the app.'
    : state === 'unsupported' ? 'This browser cannot show notifications. On an iPhone, open this site in Safari, tap Share, then Add to Home Screen, and open it from there.'
    : state === 'blocked' ? 'Notifications are blocked for this site. Allow them in your browser or phone settings, then come back here.'
    : 'Get a pop-up on this phone when a reminder is due, even when the app is closed. Applies to this device only.'

  return (
    <>
      <Toggle
        checked={state === 'on'}
        disabled={busy || state === 'loading' || state === 'unsupported' || state === 'blocked' || serverOff}
        onChange={(v) => void (v ? turnOn() : turnOff())}
        label="Notify me on this phone"
        description={description}
      />
      {state === 'on' && !serverOff && (
        <div className="py-3">
          <Button size="sm" onClick={() => void sendTest()} disabled={busy}><Bell className="size-4" aria-hidden /> Send a test notification</Button>
        </div>
      )}
    </>
  )
}
