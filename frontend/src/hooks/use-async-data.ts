import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError } from '@/lib/api'

interface AsyncState<T> {
  data: T | null
  error: ApiError | null
  loading: boolean
}

interface AsyncResult<T> extends AsyncState<T> {
  /** Re-run the fetcher. `quiet` skips the loading state for background refreshes. */
  reload: (quiet?: boolean) => Promise<void>
  setData: (data: T | null) => void
}

/** Runs an async fetcher and tracks loading/error state.
 *
 *  Requests are keyed by the caller-supplied `fetcher` identity, and a stale
 *  response is discarded rather than applied — without that, quickly changing a
 *  filter can leave the table showing results for the previous query.
 */
export function useAsyncData<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  { immediate = true }: { immediate?: boolean } = {},
): AsyncResult<T> {
  const [state, setState] = useState<AsyncState<T>>({
    data: null,
    error: null,
    loading: immediate,
  })

  const abortRef = useRef<AbortController>()
  const requestId = useRef(0)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      abortRef.current?.abort()
    }
  }, [])

  const reload = useCallback(
    async (quiet = false) => {
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller
      const id = ++requestId.current

      if (!quiet) setState((current) => ({ ...current, loading: true, error: null }))

      try {
        const data = await fetcher(controller.signal)
        if (!mounted.current || id !== requestId.current) return
        setState({ data, error: null, loading: false })
      } catch (caught) {
        if (!mounted.current || id !== requestId.current) return
        if (caught instanceof DOMException && caught.name === 'AbortError') return
        setState((current) => ({
          data: current.data,
          loading: false,
          error:
            caught instanceof ApiError
              ? caught
              : new ApiError('unknown', 'Could not load that data.', 0, true),
        }))
      }
    },
    [fetcher],
  )

  useEffect(() => {
    if (immediate) void reload()
  }, [reload, immediate])

  const setData = useCallback((data: T | null) => {
    setState((current) => ({ ...current, data }))
  }, [])

  return { ...state, reload, setData }
}
