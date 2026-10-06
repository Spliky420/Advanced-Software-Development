// The MCP and RAG reachability lights in the page header.
//
// Both are driven by this app's own backend (/api/mcp/health and
// /api/rag/health), which answer 200 whatever the news is -- a light that
// cannot report "off" would not be a status light. Each probe uses a short
// timeout on the server side, so an absent host process does not hold up the
// page.
//
// Three states, because "switched off" and "tried and could not reach it" are
// different things and a marker should be able to tell them apart at a
// glance:
//
//   ready        enabled and reachable
//   unreachable  enabled, but the host process is not answering
//   off          disabled by configuration (MCP_ENABLED / RAG_ENABLED)

import { useEffect, useState } from 'react'
import * as api from '../api/client'

function state(status) {
  if (!status) return 'unknown'
  if (!status.enabled) return 'off'
  return status.reachable ? 'ready' : 'unreachable'
}

const WORDING = {
  ready: 'ready',
  unreachable: 'unreachable',
  off: 'off',
  unknown: 'checking...',
}

function Light({ name, status, error }) {
  const condition = error ? 'unreachable' : state(status)
  const detail = error
    ? error.message
    : status?.detail || `${name} is ${WORDING[condition]} at ${status?.server_url || 'its configured URL'}`

  return (
    <span className={`service-light service-light--${condition}`} title={detail}>
      <span className="service-light__dot" aria-hidden="true" />
      {name}
      <span className="service-light__word">{WORDING[condition]}</span>
    </span>
  )
}

export default function ServiceStatus() {
  const [mcp, setMcp] = useState({ status: null, error: null })
  const [rag, setRag] = useState({ status: null, error: null })

  useEffect(() => {
    let cancelled = false

    const probe = (load, set) =>
      load()
        .then((status) => {
          if (!cancelled) set({ status, error: null })
        })
        .catch((error) => {
          if (!cancelled) set({ status: null, error })
        })

    // Not a polling loop. These report whether an optional integration is
    // up, which changes when someone starts or stops a host process -- a
    // page reload is the honest trigger for re-checking, and a timer would
    // add background traffic for no benefit.
    probe(api.getMcpHealth, setMcp)
    probe(api.getRagHealth, setRag)

    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="service-status" role="status" aria-label="Integration status">
      <Light name="MCP" status={mcp.status} error={mcp.error} />
      <Light name="RAG" status={rag.status} error={rag.error} />
    </div>
  )
}
