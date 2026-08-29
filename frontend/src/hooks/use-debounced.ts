import { useEffect, useState } from 'react'

/** Delays propagating a rapidly changing value.
 *
 *  Used by the admin search fields so typing does not fire one request per
 *  keystroke.
 */
export function useDebounced<T>(value: T, delayMs = 350): T {
  const [debounced, setDebounced] = useState(value)

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs)
    return () => window.clearTimeout(timer)
  }, [value, delayMs])

  return debounced
}
