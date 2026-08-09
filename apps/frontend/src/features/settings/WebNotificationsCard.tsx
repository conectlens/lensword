/**
 * The one place in the app that asks a browser for notification permission
 * (issue #345).
 *
 * Deliberately a click, never an effect. `Notification.requestPermission()`
 * gets one chance per origin — a denial is permanent and no later call
 * re-prompts — so asking on page load would spend the user's only answer
 * before they had been told what they were agreeing to.
 *
 * Every state a browser can be in has its own copy, because the failure modes
 * here are ones a user cannot debug from a dead toggle: a blocked permission
 * can only be undone in browser settings, and an unsupported browser will
 * never work no matter what the user clicks.
 */

import { useState } from 'react'

import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Toggle } from '../../components/ui/Toggle'
import { WEB_NOTIFICATIONS_CHANGED_EVENT } from '../../lib/useWebNotifications'
import {
  currentPermission,
  isEnabled,
  requestPermission,
  setEnabled,
  webNotificationSupport,
} from '../../lib/webNotifications'

export function WebNotificationsCard() {
  const support = webNotificationSupport()
  // Lazy initializers rather than an effect: both reads touch `window`, and
  // doing them once at mount is exactly what a lazy initializer is for. An
  // effect would render a wrong first frame and then correct it.
  const [permission, setPermission] = useState<NotificationPermission | null>(() => currentPermission())
  const [enabled, setEnabledState] = useState(() => isEnabled())
  const [busy, setBusy] = useState(false)

  // The desktop shell raises OS notifications itself and serves this same
  // build, so offering a second switch here would only let a user turn on
  // duplicates of what they already get.
  if (support === 'desktop-shell') return null

  function announce() {
    window.dispatchEvent(new Event(WEB_NOTIFICATIONS_CHANGED_EVENT))
  }

  async function enable() {
    setBusy(true)
    try {
      // Requested from this click and nowhere else.
      const result = await requestPermission()
      setPermission(result)
      if (result === 'granted') {
        setEnabled(true)
        setEnabledState(true)
      }
    } finally {
      setBusy(false)
      announce()
    }
  }

  function toggle(next: boolean) {
    setEnabled(next)
    setEnabledState(next)
    announce()
  }

  return (
    <Card className="p-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="font-display text-lg font-bold text-white">Browser notifications</h2>
          <p className="mt-1 text-sm text-white/50">
            Get reminded in this browser when words are due for review. Notifications appear only
            while LensWord is open in a tab, and only in this browser — you can turn them on
            separately on another device.
          </p>
        </div>
        {support === 'supported' && permission === 'granted' && (
          <Toggle checked={enabled} onChange={toggle} />
        )}
      </div>

      {support === 'unsupported' && (
        <p className="mt-3 text-sm text-white/50">
          This browser does not support notifications. Reminders still build up in LensWord and are
          waiting for you the next time you open it.
        </p>
      )}

      {support === 'insecure-context' && (
        <p className="mt-3 text-sm text-white/50">
          Browsers only allow notifications on secure (HTTPS) pages, so they cannot be enabled on
          this address.
        </p>
      )}

      {support === 'supported' && permission === 'default' && (
        <div className="mt-4">
          <Button size="sm" onClick={() => void enable()} disabled={busy}>
            {busy ? 'Waiting for your browser…' : 'Turn on notifications'}
          </Button>
          <p className="mt-2 text-sm text-white/50">
            Your browser will ask you to allow notifications. It only asks once, so if you dismiss
            or block it you will need to change it in your browser&rsquo;s site settings afterwards.
          </p>
        </div>
      )}

      {support === 'supported' && permission === 'denied' && (
        <p role="alert" className="mt-3 text-sm text-warning">
          Notifications are blocked for LensWord in this browser. Browsers do not allow a site to
          ask again once blocked, so this has to be changed in your browser&rsquo;s site settings
          for this page &mdash; usually behind the padlock or icon next to the address bar.
        </p>
      )}

      {support === 'supported' && permission === 'granted' && !enabled && (
        <p className="mt-3 text-sm text-white/50">
          Your browser allows notifications. Use the switch above to start receiving them here.
        </p>
      )}
    </Card>
  )
}
