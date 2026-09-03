import { useState } from 'react'
import * as api from '../api/client'
import { useAction } from '../hooks'
import { Feedback } from './common'
import { money, percent, signedMoney } from '../format'

// Total monthly commitment across active goals against the monthly budget.
//
// Every figure here comes from GET /api/budget/summary. The panel does no
// arithmetic of its own -- not even the difference -- because the backend
// already computed it and two implementations of the same sum is how they
// drift apart.
export default function BudgetPanel({ summary, userId, onSaved }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(String(summary.monthly_budget ?? ''))
  const { busy, error, run } = useAction()

  const currency = summary.currency
  const isOver = summary.status === 'over_budget'
  const notSet = summary.status === 'no_budget_set'

  const save = async () => {
    const saved = await run(() =>
      api.putBudgetSettings({ monthly_budget: Number(draft), user_id: userId, currency }),
    )
    if (saved) {
      setEditing(false)
      onSaved()
    }
  }

  return (
    <section className="panel" aria-labelledby="budget-heading">
      <div className="panel-header">
        <h2 id="budget-heading">Monthly budget</h2>
        {!editing && (
          <button type="button" className="btn btn--small btn--secondary" onClick={() => setEditing(true)}>
            {notSet ? 'Set a budget' : 'Change budget'}
          </button>
        )}
      </div>

      <Feedback error={error} />

      {editing ? (
        <div className="field-row u-mt-md">
          <div className="field">
            <label htmlFor="monthly_budget">Monthly budget ({currency})</label>
            <input
              id="monthly_budget"
              type="number"
              min="0"
              step="0.01"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
            />
          </div>
          <div className="field btn-row" style={{ alignSelf: 'end' }}>
            <button type="button" className="btn" onClick={save} disabled={busy}>
              {busy ? 'Saving...' : 'Save'}
            </button>
            <button
              type="button"
              className="btn btn--secondary"
              onClick={() => {
                setDraft(String(summary.monthly_budget ?? ''))
                setEditing(false)
              }}
              disabled={busy}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="budget-figures">
            <div>
              <span className="figure__label">Committed each month</span>
              <span className="figure__value">{money(summary.total_monthly_commitment, currency)}</span>
            </div>
            <div>
              <span className="figure__label">Your budget</span>
              <span className="figure__value">
                {notSet ? 'Not set' : money(summary.monthly_budget, currency)}
              </span>
            </div>
            <div>
              <span className="figure__label">{isOver ? 'Over by' : 'Left over'}</span>
              <span className={`figure__value ${isOver ? 'figure__value--over' : 'figure__value--under'}`}>
                {summary.difference === null ? '--' : money(Math.abs(summary.difference), currency)}
              </span>
            </div>
            <div>
              <span className="figure__label">Budget used</span>
              <span className="figure__value">
                {summary.percent_of_budget_used === null ? '--' : percent(summary.percent_of_budget_used)}
              </span>
            </div>
          </div>

          {isOver && (
            <div className="callout callout--warning" role="alert">
              <strong>Your goals need more than your budget allows.</strong> Across{' '}
              {summary.active_goal_count} active goal{summary.active_goal_count === 1 ? '' : 's'} you need{' '}
              {money(summary.total_monthly_commitment, currency)} a month against a budget of{' '}
              {money(summary.monthly_budget, currency)} &mdash; {signedMoney(summary.difference, currency)}.
              Push a target date out, lower a target, or pause a lower-priority goal.
            </div>
          )}
          {notSet && (
            <div className="callout callout--info">
              No monthly budget recorded yet. Set one and this panel will tell you whether your goals fit
              inside it.
            </div>
          )}
          {!isOver && !notSet && (
            <div className="callout callout--success">
              Your active goals fit inside your budget, with{' '}
              {money(summary.difference, currency)} a month to spare.
            </div>
          )}

          {summary.goals.length > 0 && (
            <table className="table u-mt-md">
              <caption className="muted u-mb-sm" style={{ captionSide: 'top', textAlign: 'left' }}>
                What each active goal needs per month, calculated as the amount still to save divided by the
                months left.
              </caption>
              <thead>
                <tr>
                  <th scope="col">Goal</th>
                  <th scope="col" className="numeric">
                    Still to save
                  </th>
                  <th scope="col" className="numeric">
                    Months left
                  </th>
                  <th scope="col" className="numeric">
                    Per month
                  </th>
                </tr>
              </thead>
              <tbody>
                {summary.goals.map((goal) => (
                  <tr key={goal.goal_id}>
                    <th scope="row">
                      {goal.name}
                      {goal.overdue && <span className="badge badge--behind u-mt-sm"> overdue</span>}
                    </th>
                    <td className="numeric">{money(goal.remaining_amount, currency)}</td>
                    <td className="numeric">{goal.months_remaining}</td>
                    <td className="numeric">{money(goal.required_monthly, currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  )
}
