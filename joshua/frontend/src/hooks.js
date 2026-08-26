import { useCallback, useEffect, useState } from 'react'

// Load-on-mount fetching with the three states every screen needs: loading,
// error and data. `reload` is stable, so screens can re-run a load after a
// mutation without re-triggering the effect.
export function useLoader(loadFn, deps = []) {
  const [state, setState] = useState({ status: 'loading', data: null, error: null })

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(loadFn, deps)

  const load = useCallback(() => {
    let cancelled = false
    setState({ status: 'loading', data: null, error: null })
    run()
      .then((data) => {
        if (!cancelled) setState({ status: 'ready', data, error: null })
      })
      .catch((error) => {
        if (!cancelled) setState({ status: 'error', data: null, error })
      })
    return () => {
      cancelled = true
    }
  }, [run])

  useEffect(load, [load])

  return { ...state, reload: load }
}
