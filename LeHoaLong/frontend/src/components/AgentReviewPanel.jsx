// The Agents tab: a plan reviewed by three agents, then decided by a person.
//
//   1. Python proposes. "Ask the agents" calls POST /review-plan, which builds
//      the instalment schedule in Python and sends it to the shared
//      multi-agent server. The proposal is shown at once, labelled as
//      Python's: these are the figures the agents are given and cannot change.
//   2. The agents work. The run is polled, and each stage ticks off as the
//      server stores it -- Planner, Worker, Reviewer. That progress is real:
//      the backend starts runs with "async": true, so the run id comes back
//      before any agent has run and every poll reads stored state.
//   3. A person decides. Approve or correct applies the proposal exactly as
//      reviewed; partial or reject applies nothing. The same rules the server
//      enforces are checked here first, so the form says what is missing
//      before anything is sent.
//
// Nothing here computes a figure. Every amount and date on screen comes from
// the backend as-is; the checks the Reviewer's risks open with ("Figure
// check:", "Arithmetic check:") are Python's, and are badged as such so they
// are not mistaken for the model's opinion.

import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from '../api/client'
import { BusyButton, Feedback } from './common'
import { longDate, money } from '../format'

// Fast enough that a stub run (well under a second per agent) visibly ticks
// through its stages, slow enough to be nothing for the backend: every poll
// is one read of a stored run.
const POLL_INTERVAL_MS = 1000

// The server bounds a run at three agent timeouts (3 x 55s). Past this, the
// run is not going to finish -- most likely the server was restarted -- and
// polling for ever would hide that.
const POLL_GIVE_UP_MS = 240000

const STAGES = [
  { id: 'plan', label: 'Planner', doing: 'breaking the review into steps' },
  { id: 'work', label: 'Worker', doing: 'working through each step' },
  { id: 'review', label: 'Reviewer', doing: 'checking the work for risks' },
  { id: 'human', label: 'You', doing: 'your decision' },
]

// Which stage each server status means is running now.
const ACTIVE_STAGE = { planning: 'plan', working: 'work', reviewing: 'review', awaiting_human: 'human' }
const SETTLED = ['awaiting_human', 'complete', 'failed']

const DECISIONS = [
  {
    id: 'approve',
    label: 'Approve',
    applies: true,
    hint: 'Apply the proposed instalments exactly as reviewed.',
  },
  {
    id: 'correct',
    label: 'Correct',
    applies: true,
    hint: 'Apply the instalments, with your own corrected rationale recorded in place of the agents’.',
  },
  {
    id: 'partial',
    label: 'Partially accept',
    applies: false,
    hint: 'Record which part you accept. Nothing is applied to the goal.',
  },
  { id: 'reject', label: 'Reject', applies: false, hint: 'Record the rejection. Nothing is applied to the goal.' },
]

// Remembered per goal for this browser tab, so leaving the page and coming
// back picks the review up again -- mid-run, or decided, showing what was
// decided. A new review replaces it; a run the backend no longer knows clears it. sessionStorage can be unavailable
// (private windows, blocked storage); the panel works without it.
const storageKey = (goalId) => `lehoalong.agentReview.${goalId}`
function rememberRun(goalId, runId) {
  try {
    if (runId) window.sessionStorage.setItem(storageKey(goalId), runId)
    else window.sessionStorage.removeItem(storageKey(goalId))
  } catch {
    // Not remembered; nothing else depends on it.
  }
}
function recallRun(goalId) {
  try {
    return window.sessionStorage.getItem(storageKey(goalId))
  } catch {
    return null
  }
}

function stageState(stageId, workflow) {
  if (!workflow) return 'pending'
  const order = STAGES.map((stage) => stage.id)
  const index = order.indexOf(stageId)
  if (workflow.status === 'complete') return 'done'
  if (workflow.status === 'failed') {
    const failedAt = order.indexOf(workflow.error?.phase)
    if (index < failedAt) return 'done'
    return index === failedAt ? 'failed' : 'pending'
  }
  const activeIndex = order.indexOf(ACTIVE_STAGE[workflow.status])
  if (index < activeIndex) return 'done'
  return index === activeIndex ? 'active' : 'pending'
}

const STAGE_WORD = { done: 'done', active: 'running', failed: 'failed', pending: 'waiting' }

function StageTracker({ workflow }) {
  return (
    <ol className="agent-stages" aria-label="Review progress">
      {STAGES.map((stage) => {
        const condition = stageState(stage.id, workflow)
        const waitingOnYou = stage.id === 'human' && condition === 'active'
        return (
          <li key={stage.id} className={`agent-stage agent-stage--${condition}`}>
            <span className="agent-stage__marker" aria-hidden="true">
              {condition === 'done' ? '✓' : condition === 'failed' ? '!' : ''}
            </span>
            <span className="agent-stage__label">{stage.label}</span>
            <span className="agent-stage__word">
              {waitingOnYou ? 'your turn' : condition === 'active' ? stage.doing : STAGE_WORD[condition]}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

function Proposal({ proposal }) {
  const { currency } = proposal
  return (
    <div className="agent-proposal">
      <h3 className="agent-review__heading">The proposed plan</h3>
      <p className="muted agent-review__provenance">
        Calculated in Python before any agent saw it. The agents are given these figures as final;
        nothing they write can change them.
      </p>
      <div className="budget-figures">
        <div>
          <span className="figure__label">Instalments</span>
          <span className="figure__value">
            {proposal.step_count} × {money(proposal.monthly_amount, currency)}
          </span>
          {proposal.final_amount !== proposal.monthly_amount && (
            <span className="muted figure__note">last one {money(proposal.final_amount, currency)}</span>
          )}
        </div>
        <div>
          <span className="figure__label">Finishing</span>
          <span className="figure__value">{longDate(proposal.final_due_date)}</span>
        </div>
        <div>
          <span className="figure__label">Fits the budget</span>
          <span className="figure__value">
            {proposal.within_budget === null ? (
              <span className="muted">no budget set</span>
            ) : proposal.within_budget ? (
              <span className="badge badge--ahead">yes</span>
            ) : (
              <span className="badge badge--behind">no</span>
            )}
          </span>
        </div>
        {proposal.shortfall > 0 && (
          <div>
            <span className="figure__label">Short by, each month</span>
            <span className="figure__value figure__value--over">{money(proposal.shortfall, currency)}</span>
          </div>
        )}
      </div>
      <details className="u-mt-sm">
        <summary>Every instalment ({proposal.step_count})</summary>
        <table className="table table--compact u-mt-sm">
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">Due</th>
              <th scope="col" className="numeric">
                Amount
              </th>
            </tr>
          </thead>
          <tbody>
            {proposal.steps.map((step) => (
              <tr key={step.step_order}>
                <td>{step.step_order}</td>
                <td>{longDate(step.due_date)}</td>
                <td className="numeric">{money(step.step_amount, currency)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  )
}

// A risk the backend's Python checks wrote, rather than the Reviewer model.
const PYTHON_CHECK = /^(Figure check|Arithmetic check):/

function AgentOutput({ workflow }) {
  const { plan, work, review } = workflow
  if (!plan.length && !work && !review.risks.length) return null
  return (
    <div className="agent-output">
      <h3 className="agent-review__heading">
        What the agents said{' '}
        <span className="muted">
          ({workflow.stub ? 'stub agents, no model' : `model ${workflow.model}`})
        </span>
      </h3>

      {plan.length > 0 && (
        <section className="agent-output__block" aria-label="Planner">
          <h4>Planner</h4>
          <ol>
            {plan.map((step) => (
              <li key={step.step}>
                {step.action}
                {step.evidence.length > 0 && (
                  <span className="muted agent-output__evidence"> — uses {step.evidence.join(', ')}</span>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}

      {work && (
        <section className="agent-output__block" aria-label="Worker">
          <h4>Worker</h4>
          <p className="agent-output__text">{work}</p>
        </section>
      )}

      {(review.risks.length > 0 || review.recommendations.length > 0) && (
        <section className="agent-output__block" aria-label="Reviewer">
          <h4>Reviewer</h4>
          {review.risks.length > 0 && (
            <>
              <p className="agent-output__subhead">Risks</p>
              <ul>
                {review.risks.map((risk) => (
                  <li key={risk}>
                    {PYTHON_CHECK.test(risk) && (
                      <span className="badge agent-output__check" title="Written by a Python check, not the model">
                        Python check
                      </span>
                    )}{' '}
                    {risk}
                  </li>
                ))}
              </ul>
            </>
          )}
          {review.recommendations.length > 0 && (
            <>
              <p className="agent-output__subhead">Recommendations</p>
              <ul>
                {review.recommendations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}
    </div>
  )
}

function DecisionForm({ review, onDecided, onRefresh }) {
  // Approve is the default only when it is allowed; a stale proposal opens on
  // reject rather than on a choice that cannot be submitted.
  const [decision, setDecision] = useState(review.can_apply ? 'approve' : 'reject')
  const [note, setNote] = useState('')
  const [corrected, setCorrected] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const chosen = DECISIONS.find((item) => item.id === decision)
  const blocked = chosen.applies && !review.can_apply
  // The backend's rules, checked here so the form explains itself before a
  // request is made. The backend checks them again regardless.
  const missing =
    decision === 'correct' && !corrected.trim()
      ? 'Write the corrected rationale to record.'
      : decision === 'partial' && !note.trim()
        ? 'Say which part you accept.'
        : null

  const submit = async (event) => {
    event.preventDefault()
    if (missing || blocked) return
    setBusy(true)
    setError(null)
    try {
      const payload = { decision, note: note.trim() }
      if (decision === 'correct') payload.corrected = corrected.trim()
      onDecided(await api.decidePlanReview(review.run_id, payload))
    } catch (caught) {
      setError(caught)
      // A 409 means the goal or the run changed under the form; re-read the
      // review so the stale reasons and the allowed choices are current.
      if (caught.status === 409) onRefresh()
    } finally {
      setBusy(false)
    }
  }

  const pending = review.proposal.step_count
  const submitLabel = chosen.applies
    ? `${chosen.label} and apply ${pending} instalment${pending === 1 ? '' : 's'}`
    : `${chosen.label} — apply nothing`

  return (
    <form className="agent-decision" onSubmit={submit}>
      <h3 className="agent-review__heading">Your decision</h3>

      {review.stale.is_stale && (
        <div className="callout callout--warning">
          <strong>The goal has changed since the agents reviewed this plan.</strong>
          <ul>
            {review.stale.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
          The proposal would no longer close the gap it was built for, so it cannot be applied. Reject
          it, or ask the agents again.
        </div>
      )}

      <fieldset className="agent-decision__choices">
        <legend className="sr-only">Decision</legend>
        {DECISIONS.map((item) => {
          const disabled = item.applies && !review.can_apply
          return (
            <label
              key={item.id}
              className={`agent-choice ${decision === item.id ? 'agent-choice--chosen' : ''} ${disabled ? 'agent-choice--disabled' : ''}`}
            >
              <input
                type="radio"
                name="decision"
                value={item.id}
                checked={decision === item.id}
                disabled={disabled}
                onChange={() => setDecision(item.id)}
              />
              <span className="agent-choice__label">{item.label}</span>
              <span className="agent-choice__hint muted">{item.hint}</span>
            </label>
          )
        })}
      </fieldset>

      {decision === 'correct' && (
        <div className="field">
          <label htmlFor="agent-corrected">Corrected rationale (required)</label>
          <textarea
            id="agent-corrected"
            rows={3}
            maxLength={2000}
            value={corrected}
            onChange={(event) => setCorrected(event.target.value)}
            placeholder="What the agents got wrong, and the reasoning you are approving the plan on."
          />
        </div>
      )}

      {decision !== 'correct' && (
        <div className="field">
          <label htmlFor="agent-note">
            {decision === 'partial' ? 'Which part you accept (required)' : 'Note (optional)'}
          </label>
          <textarea
            id="agent-note"
            rows={2}
            maxLength={1000}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </div>
      )}

      {missing && <p className="field__hint">{missing}</p>}
      <Feedback error={error} />

      <div className="btn-row">
        <BusyButton
          type="submit"
          className={chosen.applies ? 'btn' : 'btn btn--secondary'}
          busy={busy}
          busyLabel="Recording..."
          disabled={Boolean(missing) || blocked}
        >
          {submitLabel}
        </BusyButton>
      </div>
    </form>
  )
}

function Outcome({ decision, currency }) {
  return (
    <div className={`callout ${decision.applied ? 'callout--success' : 'callout--info'}`} role="status">
      <strong>
        {decision.applied
          ? `${decision.decision === 'correct' ? 'Corrected and applied' : 'Approved and applied'}: ${decision.steps_applied} instalment${decision.steps_applied === 1 ? '' : 's'} are now the plan.`
          : `${decision.decision === 'partial' ? 'Partially accepted' : 'Rejected'}. Nothing was applied to the goal.`}
      </strong>
      {(decision.rationale || decision.corrected || decision.note) && (
        <div className="u-mt-sm">Recorded: “{decision.rationale || decision.corrected || decision.note}”</div>
      )}
      {decision.applied && (
        <div className="u-mt-sm muted">The savings plan below now shows them, in {currency}.</div>
      )}
    </div>
  )
}

export default function AgentReviewPanel({ goalId, currency, onPlanned }) {
  const [started, setStarted] = useState(null) // the POST /review-plan body
  const [review, setReview] = useState(null) // the latest GET /workflow body
  const [decided, setDecided] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [gaveUp, setGaveUp] = useState(false)
  const timer = useRef(null)
  const pollingSince = useRef(0)

  const stopPolling = () => {
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = null
  }

  const poll = useCallback(async (runId) => {
    stopPolling()
    try {
      const body = await api.getPlanReview(runId)
      setReview(body)
      setError(null)
      if (body.decision) setDecided({ ...body.decision, run_id: runId })
      if (SETTLED.includes(body.workflow.status)) return
    } catch (caught) {
      setError(caught)
      // A 404 means the run is gone for good; anything else may pass.
      if (caught.isNotFound) {
        rememberRun(goalId, null)
        return
      }
    }
    if (Date.now() - pollingSince.current > POLL_GIVE_UP_MS) {
      setGaveUp(true)
      return
    }
    timer.current = window.setTimeout(() => poll(runId), POLL_INTERVAL_MS)
  }, [goalId])

  // Pick a run up again after navigating away and back.
  useEffect(() => {
    const runId = recallRun(goalId)
    if (runId) {
      pollingSince.current = Date.now()
      poll(runId)
    }
    return stopPolling
  }, [goalId, poll])

  const start = async () => {
    stopPolling()
    setBusy(true)
    setError(null)
    setReview(null)
    setDecided(null)
    setGaveUp(false)
    try {
      const body = await api.startPlanReview(goalId)
      setStarted(body)
      const runId = body.review.run_id
      rememberRun(goalId, runId)
      if (runId) {
        pollingSince.current = Date.now()
        poll(runId)
      }
    } catch (caught) {
      setStarted(null)
      setError(caught)
    } finally {
      setBusy(false)
    }
  }

  const applyWithoutReview = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.generatePlan(goalId, { useMcp: true })
      setStarted(null)
      rememberRun(goalId, null)
      onPlanned()
    } catch (caught) {
      setError(caught)
    } finally {
      setBusy(false)
    }
  }

  const onDecided = (result) => {
    setDecided(result)
    if (result.applied) onPlanned()
    poll(result.run_id)
  }

  const unavailable = started?.review.status === 'unavailable'
  const proposal = review?.proposal || started?.proposal
  const workflow = review?.workflow || started?.review.workflow
  const awaiting = review && review.can_decide && !decided
  const running = workflow && !SETTLED.includes(workflow.status) && !gaveUp

  return (
    <div className="agent-review">
      <p className="muted">
        Python works out the plan first, every amount and date. Three agents on the shared
        multi-agent server then review it: a Planner breaks the review into steps, a Worker carries
        them out against the figures, and a Reviewer names the risks. None of them is asked for a
        number. Nothing changes on this goal until you decide.
      </p>

      <div className="btn-row">
        <BusyButton busy={busy} busyLabel="Starting..." onClick={start} disabled={Boolean(running)}>
          {workflow || unavailable ? 'Ask the agents again' : 'Ask the agents to review a plan'}
        </BusyButton>
      </div>

      <Feedback error={error} />

      {unavailable && (
        <div className="callout callout--warning u-mt-md">
          <strong>The agents are not available, so no review was started.</strong>
          <div className="u-mt-sm">{started.review.reason}</div>
          <div className="u-mt-sm">
            The plan below is still Python&apos;s and still correct. You can apply it without a review, as
            Release 1 did, or try the agents again later.
          </div>
          <div className="btn-row u-mt-sm">
            <BusyButton className="btn btn--secondary" busy={busy} busyLabel="Applying..." onClick={applyWithoutReview}>
              Apply without review
            </BusyButton>
          </div>
        </div>
      )}

      {workflow && (
        <>
          <StageTracker workflow={workflow} />
          {workflow.status === 'failed' && (
            <div className="callout callout--warning">
              <strong>The {workflow.error?.phase} agent could not run.</strong>
              <div className="u-mt-sm">{workflow.error?.detail}</div>
              <div className="u-mt-sm">Nothing was applied. Ask the agents again, or plan from the AI-Mode tab.</div>
            </div>
          )}
          {gaveUp && (
            <div className="callout callout--warning">
              The agents have taken longer than their time limits allow, so this page has stopped waiting. The
              multi-agent server may have been restarted; ask the agents again.
            </div>
          )}
        </>
      )}

      {proposal && <Proposal proposal={proposal} />}
      {workflow && <AgentOutput workflow={workflow} />}

      {awaiting && (
        // Keyed on staleness so the form resets its default choice when a
        // refresh finds the proposal can no longer be applied.
        <DecisionForm
          key={`${review.run_id}-${review.can_apply}`}
          review={review}
          onDecided={onDecided}
          onRefresh={() => poll(review.run_id)}
        />
      )}
      {decided && <Outcome decision={decided} currency={currency} />}
    </div>
  )
}
