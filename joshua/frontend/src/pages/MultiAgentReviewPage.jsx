import { useEffect, useState } from 'react'
import { getMultiAgentRun, startMultiAgentReview, submitMultiAgentReview } from '../api'
import { AiLoading, EmptyState, ErrorBanner, WarningBanner } from '../components/Feedback'

// The shared Multi-Agent Server runs Planner -> Worker -> Reviewer inside one
// request, then waits for a person. Each stage gets its own labelled section,
// the same way the drift review shows its phases. The `tone` reuses the drift
// review's phase colours.
const STAGES = [
  { key: 'planner', tone: 'plan', step: 1, title: 'Planner', tagline: 'Break the task into steps' },
  { key: 'worker', tone: 'act', step: 2, title: 'Worker', tagline: 'Carry out each step' },
  { key: 'reviewer', tone: 'observe', step: 3, title: 'Reviewer', tagline: 'Check the work for risks' },
  { key: 'human', tone: 'adapt', step: 4, title: 'Human review', tagline: 'Your decision completes the run' },
]

const DECISIONS = [
  { value: 'approve', label: 'Approve', hint: 'Accept the agents’ output as it is.' },
  { value: 'correct', label: 'Correct', hint: 'Replace the output with your corrected text.' },
  { value: 'partial', label: 'Partially accept', hint: 'Say in the note which part you accept.' },
  { value: 'reject', label: 'Reject', hint: 'Do not accept the output.' },
]

function StageSection({ stage, children }) {
  return (
    <section className={`phase phase-${stage.tone}`} aria-labelledby={`stage-${stage.key}`}>
      <header className="phase-header">
        <span className="phase-step" aria-hidden="true">
          {stage.step}
        </span>
        <div>
          <h3 id={`stage-${stage.key}`} className="phase-title">
            <span className="phase-label">Stage {stage.step}</span>
            {stage.title}
          </h3>
          <p className="phase-tagline">{stage.tagline}</p>
        </div>
      </header>
      <div className="phase-body">{children}</div>
    </section>
  )
}

function ItemList({ items, empty }) {
  if (!items || items.length === 0) return <EmptyState>{empty}</EmptyState>
  return (
    <ul className="banner-list">
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  )
}

// Mirrors the server's rules so the common mistakes are caught before a
// round trip; the server still has the final say and its errors are shown too.
function validateReview({ decision, note, corrected }) {
  const errors = {}
  if (!decision) errors.decision = 'Choose a decision.'
  if (decision === 'partial' && !note.trim()) errors.note = 'Say which part you accept.'
  if (decision === 'correct' && !corrected.trim()) errors.corrected = 'Enter the corrected text.'
  return errors
}

function ReviewForm({ runId, onDecided }) {
  const [decision, setDecision] = useState('')
  const [note, setNote] = useState('')
  const [corrected, setCorrected] = useState('')
  const [fieldErrors, setFieldErrors] = useState({})
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    const errors = validateReview({ decision, note, corrected })
    setFieldErrors(errors)
    if (Object.keys(errors).length > 0) return

    const body = { decision }
    if (note.trim()) body.note = note.trim()
    if (decision === 'correct') body.corrected = corrected.trim()

    setSaving(true)
    setError(null)
    try {
      onDecided(await submitMultiAgentReview(runId, body), body)
    } catch (failure) {
      setError(failure)
      if (failure.fields) setFieldErrors(failure.fields)
    } finally {
      setSaving(false)
    }
  }

  const fieldClass = (name) => (fieldErrors[name] ? 'form-field form-field-invalid' : 'form-field')

  return (
    <form className="form" onSubmit={handleSubmit} noValidate>
      <fieldset className={`${fieldClass('decision')} decision-options`}>
        <legend>Decision</legend>
        {DECISIONS.map((option) => (
          <label key={option.value} className="decision-option">
            <input
              type="radio"
              name="decision"
              value={option.value}
              checked={decision === option.value}
              onChange={() => setDecision(option.value)}
            />
            <span>
              <strong>{option.label}</strong> <span className="form-hint">{option.hint}</span>
            </span>
          </label>
        ))}
        {fieldErrors.decision && <p className="form-error">{fieldErrors.decision}</p>}
      </fieldset>

      <div className={fieldClass('note')}>
        <label htmlFor="review-note">
          Note{decision === 'partial' ? ' (required)' : ' (optional)'}
        </label>
        <textarea id="review-note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
        {fieldErrors.note && <p className="form-error">{fieldErrors.note}</p>}
      </div>

      {decision === 'correct' && (
        <div className={fieldClass('corrected')}>
          <label htmlFor="review-corrected">Corrected text (required)</label>
          <textarea
            id="review-corrected"
            rows={4}
            value={corrected}
            onChange={(e) => setCorrected(e.target.value)}
          />
          {fieldErrors.corrected && <p className="form-error">{fieldErrors.corrected}</p>}
        </div>
      )}

      <ErrorBanner error={error} title="The decision could not be recorded" />

      <div className="form-actions">
        <button type="submit" className="button button-primary" disabled={saving}>
          {saving ? 'Submitting...' : 'Submit decision'}
        </button>
      </div>
    </form>
  )
}

// How often to ask for the run's progress, and the most time to wait in all.
// The server bounds a run at three agent timeouts (3 x 55s); 180s sits above
// that, in case the server restarts mid-run and the run can never finish.
const POLL_INTERVAL_MS = 2500
const POLL_DEADLINE_MS = 180000

const IN_FLIGHT = ['planning', 'working', 'reviewing']

// The three agents in order, with the run status that means each is running
// and the error.phase name the server uses when it fails.
const AGENTS = [
  { phase: 'plan', label: 'Planner', running: 'planning' },
  { phase: 'work', label: 'Worker', running: 'working' },
  { phase: 'review', label: 'Reviewer', running: 'reviewing' },
]

function agentState(run, index) {
  if (run.status === 'failed') {
    const failedAt = AGENTS.findIndex((agent) => agent.phase === run.error?.phase)
    if (index < failedAt) return 'done'
    return index === failedAt ? 'failed' : 'skipped'
  }
  if (run.status === 'lost' || run.status === 'timed_out') {
    const lastKnown = run.lastStatus
    const runningAt = AGENTS.findIndex((agent) => agent.running === lastKnown)
    if (index < runningAt) return 'done'
    return 'unknown'
  }
  const runningAt = AGENTS.findIndex((agent) => agent.running === run.status)
  if (runningAt === -1) return 'done' // awaiting_human or complete
  if (index < runningAt) return 'done'
  return index === runningAt ? 'running' : 'waiting'
}

const AGENT_STATE_LABELS = {
  done: 'Done',
  running: 'Running...',
  waiting: 'Waiting',
  failed: 'Failed',
  skipped: 'Not run',
  unknown: 'Unknown',
}

const AGENT_STATE_MARKS = { done: '✓', failed: '✗', running: '' }

function AgentProgress({ run }) {
  return (
    <ol className="agent-progress" aria-label="Agent progress">
      {AGENTS.map((agent, index) => {
        const state = agentState(run, index)
        return (
          <li key={agent.phase} className={`agent-step agent-step-${state}`} data-state={state}>
            <span className="agent-step-mark" aria-hidden="true">
              {state === 'running' ? <span className="spinner" /> : AGENT_STATE_MARKS[state] ?? '•'}
            </span>
            <strong>{agent.label}</strong>
            <span className="agent-step-state">{AGENT_STATE_LABELS[state]}</span>
          </li>
        )
      })}
    </ol>
  )
}

function DecisionBanner({ decided }) {
  return (
    <div className="banner banner-success" role="status">
      <strong className="banner-title">
        Decision recorded: {DECISIONS.find((d) => d.value === decided.decision)?.label ?? decided.decision}
      </strong>
      <p className="banner-message">
        Run <code>{decided.run_id}</code> is <strong>{decided.status}</strong> as of{' '}
        {decided.decided_at}.
      </p>
      {decided.note && <p className="banner-message">Note: {decided.note}</p>}
      {decided.corrected && <p className="banner-message">Corrected text: {decided.corrected}</p>}
    </div>
  )
}

// Marks a run the page stopped polling for its own reasons -- the server could
// not be reached, or the deadline passed -- keeping the last status it saw.
function stopped(current, status) {
  return current && { ...current, run: { ...current.run, lastStatus: current.run.status, status } }
}

export default function MultiAgentReviewPage() {
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [starting, setStarting] = useState(false)
  const [decided, setDecided] = useState(null)

  const run = result?.run
  const polling = Boolean(run && IN_FLIGHT.includes(run.status))
  const runId = run?.run_id
  const runStatus = run?.status
  const startedAt = result?.startedAt

  // One poll per render while the run is in flight; each answer re-renders
  // and schedules the next. Stops at awaiting_human, complete or failed, on
  // any request error, at the deadline, and when the page unmounts.
  useEffect(() => {
    if (!polling) return undefined
    let cancelled = false
    const timer = setTimeout(async () => {
      if (Date.now() - startedAt > POLL_DEADLINE_MS) {
        setError({
          message:
            'The agents did not finish within 3 minutes. The Multi-Agent Server may have ' +
            'restarted, or the model is very slow. Start a new review to try again.',
        })
        setResult((current) => stopped(current, 'timed_out'))
        return
      }
      try {
        const latest = await getMultiAgentRun(runId)
        if (!cancelled) setResult((current) => current && { ...current, run: latest.run, polls: (current.polls ?? 0) + 1 })
      } catch (failure) {
        if (!cancelled) {
          setError(failure)
          setResult((current) => stopped(current, 'lost'))
        }
      }
    }, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [polling, runId, runStatus, result?.polls, startedAt])

  async function start() {
    setStarting(true)
    setError(null)
    setResult(null)
    setDecided(null)
    try {
      const started = await startMultiAgentReview()
      setResult({ ...started, startedAt: Date.now(), polls: 0 })
    } catch (failure) {
      setError(failure)
    } finally {
      setStarting(false)
    }
  }

  const finished = run && (run.status === 'awaiting_human' || run.status === 'complete')
  const failed = run?.status === 'failed'
  const failedAgent = failed ? AGENTS.find((agent) => agent.phase === run.error?.phase) : null
  const stageByKey = Object.fromEntries(STAGES.map((stage) => [stage.key, stage]))
  const busy = starting || polling

  return (
    <section className="page">
      <header className="page-header">
        <h2>Multi-Agent Review</h2>
        <button type="button" className="button button-primary" onClick={start} disabled={busy}>
          {busy ? 'Running...' : run ? 'Start a new review' : 'Start Multi-Agent Review'}
        </button>
      </header>

      <p className="page-intro">
        Sends your holdings, allocation and drift figures -- all computed in Python -- to the
        team&rsquo;s shared Multi-Agent Server. A Planner, a Worker and a Reviewer agent work
        through the task &ldquo;{result?.task ?? 'Review my portfolio allocation and drift'}&rdquo;
        in turn. No agent calculates a figure. The run is only complete once you record a
        decision.
      </p>

      {busy && (
        <AiLoading
          label={starting ? 'Starting the agents...' : 'The agents are working...'}
          note="Three agents run one after another, so this can take up to a few minutes."
        />
      )}

      {run && <AgentProgress run={run} />}

      <ErrorBanner
        error={error}
        title={run ? 'Lost contact with the Multi-Agent Review' : 'The Multi-Agent Review could not be run'}
      />

      {failed && (
        <div className="banner banner-error" role="alert">
          <h3 className="banner-title">
            The {failedAgent?.label ?? 'agent'} could not run, so this review stopped
          </h3>
          <p className="banner-message">{run.error?.detail}</p>
          <p className="banner-hint">
            Check Ollama is running on the host with the model pulled, or start the Multi-Agent
            Server with <code>STUB_AGENTS=true</code>. Then start a new review.
          </p>
        </div>
      )}

      {!run && !busy && !error && (
        <EmptyState>Start a review to see the plan, the work and the review.</EmptyState>
      )}

      {finished && (
        <div className="phase-list">
          {run.stub && (
            <WarningBanner>
              <strong className="banner-title">Stub agents</strong>
              <p className="banner-message">
                The Multi-Agent Server is running with <code>STUB_AGENTS=true</code>, so this output
                is canned and no model was called.
              </p>
            </WarningBanner>
          )}

          <dl className="phase-facts">
            <div>
              <dt>Run</dt>
              <dd>
                <code>{run.run_id}</code>
              </dd>
            </div>
            <div>
              <dt>Model</dt>
              <dd>
                <code>{run.model}</code>
              </dd>
            </div>
            <div>
              <dt>Holdings sent</dt>
              <dd>{result.evidence.holdings.length}</dd>
            </div>
            <div>
              <dt>Drift breaches sent</dt>
              <dd>{result.evidence.drift.breaches.length}</dd>
            </div>
          </dl>

          <StageSection stage={stageByKey.planner}>
            {run.plan.length === 0 ? (
              <EmptyState>The planner returned no steps.</EmptyState>
            ) : (
              <ol className="banner-list">
                {run.plan.map((step) => (
                  <li key={step.step}>
                    {step.action}
                    {step.evidence?.length > 0 && (
                      <span className="form-hint"> (evidence: {step.evidence.join(', ')})</span>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </StageSection>

          <StageSection stage={stageByKey.worker}>
            <article className="ai-result">
              <p className="ai-text worker-output">{run.work || 'The worker returned no output.'}</p>
            </article>
          </StageSection>

          <StageSection stage={stageByKey.reviewer}>
            <h4 className="phase-subheading">Risks</h4>
            <ItemList items={run.review?.risks} empty="No risks reported." />
            <h4 className="phase-subheading">Recommendations</h4>
            <ItemList items={run.review?.recommendations} empty="No recommendations." />
          </StageSection>

          <StageSection stage={stageByKey.human}>
            {decided || run.human_review ? (
              <DecisionBanner
                decided={decided ?? { run_id: run.run_id, status: run.status, ...run.human_review }}
              />
            ) : (
              <ReviewForm
                runId={run.run_id}
                onDecided={(response, sent) =>
                  setDecided({ ...response, ...sent, decision: response.decision })
                }
              />
            )}
          </StageSection>
        </div>
      )}
    </section>
  )
}
