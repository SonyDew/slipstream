import { useEffect, useRef } from 'react'

/** Calls `callback` every `delayMs` while `enabled`.
 *
 *  The callback is held in a ref so a caller can pass an inline closure without
 *  restarting the timer on every render, which would otherwise make the
 *  interval never fire on a frequently re-rendering page.
 */
export function usePolling(
  callback: () => void | Promise<void>,
  delayMs: number,
  enabled = true,
): void {
  const latest = useRef(callback)

  useEffect(() => {
    latest.current = callback
  }, [callback])

  useEffect(() => {
    if (!enabled || delayMs <= 0) return

    let stopped = false
    let timer = 0

    const tick = async () => {
      // Skip work the user cannot see; a background tab polling the admin
      // dashboard is pure server load.
      if (document.visibilityState === 'visible') await latest.current()
      if (!stopped) timer = window.setTimeout(tick, delayMs)
    }

    timer = window.setTimeout(tick, delayMs)

    return () => {
      stopped = true
      window.clearTimeout(timer)
    }
  }, [delayMs, enabled])
}
