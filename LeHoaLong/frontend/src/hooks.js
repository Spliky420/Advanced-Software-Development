import { useCallback, useEffect, useRef, useState } from 'react'

// One place for the load / loaded / failed cycle every page repeats.
//
// `reload` is what a mutation calls once it has finished, so the page shows
// the server's version of the world rather than a guess at it.
export function useAsync(loader, deps = []) {
  const [state, setState] = useState({ loading: true, data: null, error: null })
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const run = useCallback(
    async ({ quiet = false } = {}) => {
      if (!quiet) setState((previous) => ({ ...previous, loading: true, error: null }))
      try {
        const data = await loader()
        // A response that arrives after the user has navigated away must not
        // set state on an unmounted component.
        if (mounted.current) setState({ loading: false, data, error: null })
        return data
      } catch (error) {
        if (mounted.current) setState({ loading: false, data: null, error })
        return null
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    deps,
  )

  useEffect(() => {
    run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { ...state, reload: run }
}

// For a button that fires one request and needs to show that it is working.
// The LLM calls take tens of seconds, so "busy" is a state the UI must have.
export function useAction() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const run = useCallback(async (fn) => {
    setBusy(true)
    setError(null)
    try {
      return await fn()
    } catch (caught) {
      setError(caught)
      return null
    } finally {
      setBusy(false)
    }
  }, [])

  return { busy, error, setError, run }
}
