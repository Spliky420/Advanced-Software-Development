import { useState } from 'react'
import * as api from '../api/client'
import { useAction } from '../hooks'
import { Feedback } from './common'
import { longDate, money, todayIso } from '../format'

// One row of the plan. Editable in place: amount, due date and description,
// or just tick it off.
//
// Editing the substance of an AI-written step flips its `source` to 'user' on
// the server; ticking it complete does not. The row shows which, because
// after a regeneration that provenance is the only way to tell what the model
// wrote from what you did.
function StepRow({ goalId, step, currency, onChanged }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({
    description: step.description,
    step_amount: String(step.step_amount),
    due_date: step.due_date,
  })
  const { busy, error, run } = useAction()

  const overdue = step.status === 'pending' && step.due_date <= todayIso()

  const save = async () => {
    const saved = await run(() =>
      api.updateStep(goalId, step.step_id, {
        description: draft.description.trim(),
        step_amount: Number(draft.step_amount),
        due_date: draft.due_date,
      }),
    )
    if (saved) {
      setEditing(false)
      onChanged()
    }
  }

  const setStatus = async (status) => {
    if (await run(() => api.updateStep(goalId, step.step_id, { status }))) onChanged()
  }

  const remove = async () => {
    if (await run(() => api.deleteStep(goalId, step.step_id))) onChanged()
  }

  const classes = ['step']
  if (step.status === 'complete') classes.push('step--complete')
  if (overdue) classes.push('step--overdue')

  return (
    <li className={classes.join(' ')}>
      <span className="step__order" aria-hidden="true">
        {step.status === 'complete' ? '✓' : step.step_order}
      </span>

      <div className="step__body">
        <Feedback error={error} />

        {editing ? (
          <>
            <div className="field">
              <label htmlFor={`desc-${step.step_id}`}>Description</label>
              <input
                id={`desc-${step.step_id}`}
                value={draft.description}
                maxLength={300}
                onChange={(event) => setDraft({ ...draft, description: event.target.value })}
              />
            </div>
            <div className="field-row">
              <div className="field">
                <label htmlFor={`amount-${step.step_id}`}>Amount</label>
                <input
                  id={`amount-${step.step_id}`}
                  type="number"
                  min="0"
                  step="0.01"
                  value={draft.step_amount}
                  onChange={(event) => setDraft({ ...draft, step_amount: event.target.value })}
                />
              </div>
              <div className="field">
                <label htmlFor={`due-${step.step_id}`}>Due</label>
                <input
                  id={`due-${step.step_id}`}
                  type="date"
                  value={draft.due_date}
                  onChange={(event) => setDraft({ ...draft, due_date: event.target.value })}
                />
              </div>
            </div>
            <div className="btn-row">
              <button type="button" className="btn btn--small" onClick={save} disabled={busy}>
                {busy ? 'Saving...' : 'Save step'}
              </button>
              <button
                type="button"
                className="btn btn--small btn--secondary"
                onClick={() => setEditing(false)}
                disabled={busy}
              >
                Cancel
              </button>
            </div>
          </>
        ) : (
          <>
            <span className="step__description">{step.description}</span>
            <span className="step__meta">
              <span className="step__amount">{money(step.step_amount, currency)}</span>
              <span className="step__due">
                due {longDate(step.due_date)}
                {overdue && ' (overdue)'}
              </span>
              <span>{step.source === 'ai' ? 'written by the model' : 'edited by you'}</span>
            </span>
          </>
        )}
      </div>

      {!editing && (
        <div className="step__actions">
          {step.status === 'pending' ? (
            <button
              type="button"
              className="btn btn--small"
              onClick={() => setStatus('complete')}
              disabled={busy}
            >
              Mark done
            </button>
          ) : (
            <button
              type="button"
              className="btn btn--small btn--secondary"
              onClick={() => setStatus('pending')}
              disabled={busy}
            >
              Reopen
            </button>
          )}
          <button
            type="button"
            className="btn btn--small btn--secondary"
            onClick={() => setEditing(true)}
            disabled={busy}
          >
            Edit
          </button>
          <button type="button" className="btn btn--small btn--danger" onClick={remove} disabled={busy}>
            Delete
          </button>
        </div>
      )}
    </li>
  )
}

export default function StepList({ goalId, steps, currency, onChanged }) {
  if (steps.length === 0) {
    return (
      <p className="empty-state">
        This goal has no plan yet. Generate one and the model will lay out dated instalments for you.
      </p>
    )
  }
  return (
    <ol className="step-list">
      {steps.map((step) => (
        <StepRow key={step.step_id} goalId={goalId} step={step} currency={currency} onChanged={onChanged} />
      ))}
    </ol>
  )
}
