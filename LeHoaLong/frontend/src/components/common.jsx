// Small presentational pieces shared across pages.

import { label, percent } from '../format'

// A message banner. `error` accepts an ApiError, whose `details` array is the
// per-field list a 400 comes back with -- showing all of them at once is the
// whole reason the backend collects them rather than failing on the first.
export function Feedback({ error, success, info }) {
  if (error) {
    const hint = error.isModelUnavailable
      ? 'The AI service is unavailable. Everything else on this page still works.'
      : null
    return (
      <div className="feedback feedback--error" role="alert">
        <strong>{error.message}</strong>
        {hint && <div className="u-mt-sm">{hint}</div>}
        {error.details?.length > 0 && (
          <ul>
            {error.details.map((detail) => (
              <li key={detail}>{detail}</li>
            ))}
          </ul>
        )}
      </div>
    )
  }
  if (success) {
    return (
      <div className="feedback feedback--success" role="status">
        {success}
      </div>
    )
  }
  if (info) {
    return (
      <div className="feedback feedback--info" role="status">
        {info}
      </div>
    )
  }
  return null
}

export function Loading({ what = 'data' }) {
  return (
    <p className="empty-state" role="status">
      Loading {what}...
    </p>
  )
}

export function PriorityBadge({ priority }) {
  return <span className={`badge badge--${priority}`}>{priority}</span>
}

// The on-track / behind / ahead reading from GET /progress. Rendered from the
// backend's own classification -- the browser never decides this itself.
export function StatusBadge({ status }) {
  if (!status) return null
  return <span className={`badge badge--${status}`}>{label(status)}</span>
}

// `percentComplete` is uncapped by the API, because over-funding a goal is
// real and worth reporting. The bar caps its own width so the fill cannot
// overflow its track.
export function ProgressBar({ percentComplete, status, showLabels = true, savedLabel, targetLabel }) {
  const width = Math.max(0, Math.min(100, percentComplete ?? 0))
  return (
    <div>
      <div
        className="progress"
        role="progressbar"
        aria-valuenow={Math.round(percentComplete ?? 0)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Goal progress"
      >
        <div className={`progress__fill progress__fill--${status || 'on_track'}`} style={{ width: `${width}%` }} />
      </div>
      {showLabels && (
        <div className="progress__labels">
          <span>{savedLabel}</span>
          <span>
            {percent(percentComplete)}
            {targetLabel ? ` of ${targetLabel}` : ''}
          </span>
        </div>
      )}
    </div>
  )
}

// A button that shows it is working. The plan and replan calls run a local
// model and can take tens of seconds, so a dead-looking button is not an
// option.
export function BusyButton({ busy, busyLabel, children, className = 'btn', ...rest }) {
  return (
    <button type="button" className={className} disabled={busy || rest.disabled} {...rest}>
      {busy && <span className="spinner" aria-hidden="true" />}
      {busy ? busyLabel || 'Working...' : children}
    </button>
  )
}
