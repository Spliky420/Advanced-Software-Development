// Shared loading / error / empty presentation. Every screen routes its API
// failures through ErrorBanner rather than swallowing them.

export function ErrorBanner({ error, onRetry, title }) {
  if (!error) return null

  // A 503 always means the same thing, and naming it beats whatever generic
  // title the caller passed ("the summary could not be generated" does not
  // tell the user that Ollama is what is down), so it wins over `title`.
  const aiDisabled = error.aiStatus === 'disabled'
  const heading = aiDisabled
    ? 'AI is switched off'
    : error.isLlmUnavailable
      ? 'The AI service is unavailable'
      : title || 'Something went wrong'

  return (
    <div className="banner banner-error" role="alert">
      <h3 className="banner-title">{heading}</h3>
      <p className="banner-message">{error.message}</p>

      {error.errors && error.errors.length > 1 && (
        <ul className="banner-list">
          {error.errors.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}

      {aiDisabled && (
        <p className="banner-hint">
          The backend is running with <code>AI_MODE_ENABLED=false</code>. Everything else in the
          app works as normal.
        </p>
      )}

      {error.isLlmUnavailable && !aiDisabled && (
        <p className="banner-hint">
          The rest of the app still works -- only the AI commentary needs Ollama. Check Ollama is
          running on the host and that the model in <code>OLLAMA_MODEL</code> has been pulled.
        </p>
      )}

      {onRetry && (
        <button type="button" className="button button-secondary" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}

export function WarningBanner({ children }) {
  return (
    <div className="banner banner-warning" role="status">
      {children}
    </div>
  )
}

export function Loading({ label = 'Loading...' }) {
  return (
    <p className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}
    </p>
  )
}

// The AI endpoints take up to ~45s, so they get a longer-lived indicator that
// says so rather than a bare spinner the user cannot interpret.
export function AiLoading({ label, note = 'The model runs locally in Ollama and can take up to 45 seconds.' }) {
  return (
    <div className="ai-loading" role="status">
      <span className="spinner" aria-hidden="true" />
      <div>
        <strong>{label}</strong>
        <p className="ai-loading-note">{note}</p>
      </div>
    </div>
  )
}

export function EmptyState({ children }) {
  return <p className="empty-state">{children}</p>
}
