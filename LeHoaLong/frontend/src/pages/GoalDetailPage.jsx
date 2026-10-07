import { Link, useNavigate, useParams } from 'react-router-dom'
import * as api from '../api/client'
import AiModePanel from '../components/AiModePanel'
import ContributionForm from '../components/ContributionForm'
import StepList from '../components/StepList'
import { Feedback, Loading, PriorityBadge, ProgressBar, StatusBadge } from '../components/common'
import { useAsync } from '../hooks'
import { longDate, money, percent, signedMoney } from '../format'

// The whole agentic loop for one goal, on one page:
//
//   PLAN     the AI mode panel's generate / regenerate buttons
//   ACT      the log contribution form
//   OBSERVE  the progress panel, refreshed after every change
//   ADAPT    Regenerate plan, which sends the observed variance to the model
//
// Release 1 moved the planning controls into the AI mode panel: there are now
// three ways to ask for a plan and they belong beside each other. The savings
// plan panel below shows what came out of it.
async function loadGoal(goalId) {
  const [goal, progress, budget] = await Promise.all([
    api.getGoal(goalId),
    api.getProgress(goalId),
    api.getBudgetSummary().catch(() => null),
  ])
  return { goal, progress, currency: budget?.currency || 'AUD' }
}

function ProgressPanel({ progress, currency }) {
  const behind = progress.status === 'behind'
  return (
    <section className="panel" aria-labelledby="progress-heading">
      <div className="panel-header">
        <h2 id="progress-heading">Progress</h2>
        <StatusBadge status={progress.status} />
      </div>

      <ProgressBar
        percentComplete={progress.percent_complete}
        status={progress.status}
        savedLabel={`${money(progress.saved_to_date, currency)} saved`}
        targetLabel={money(progress.target_amount, currency)}
      />

      <div className="budget-figures">
        <div>
          <span className="figure__label">Saved so far</span>
          <span className="figure__value">{money(progress.saved_to_date, currency)}</span>
        </div>
        <div>
          <span className="figure__label">The plan expected by now</span>
          <span className="figure__value">{money(progress.required_to_date, currency)}</span>
        </div>
        <div>
          <span className="figure__label">Difference</span>
          <span className={`figure__value ${behind ? 'figure__value--over' : 'figure__value--under'}`}>
            {signedMoney(progress.variance, currency)}
          </span>
        </div>
        <div>
          <span className="figure__label">Still to save</span>
          <span className="figure__value">{money(progress.remaining_amount, currency)}</span>
        </div>
      </div>

      <p className="muted">
        {progress.has_plan ? (
          <>
            {percent(progress.percent_complete)} of the way there, {progress.pending_step_count} instalment
            {progress.pending_step_count === 1 ? '' : 's'} left
            {progress.overdue_step_count > 0 && `, ${progress.overdue_step_count} overdue`}.
          </>
        ) : (
          <>No plan yet, so there is nothing to measure against.</>
        )}{' '}
        {progress.projected_completion_date ? (
          <>
            At your rate so far this lands on <strong>{longDate(progress.projected_completion_date)}</strong>
            {progress.projected_meets_target === false && ', after your target date'}.
          </>
        ) : (
          <>No contributions yet, so there is no rate to project from.</>
        )}
      </p>

      {behind && (
        <div className="callout callout--warning">
          You are {money(Math.abs(progress.variance), currency)} behind this plan. Regenerating it will spread
          what is left across the instalments that remain.
        </div>
      )}
    </section>
  )
}

export default function GoalDetailPage() {
  const { goalId } = useParams()
  const navigate = useNavigate()
  const { loading, data, error, reload } = useAsync(() => loadGoal(goalId), [goalId])

  const refresh = () => reload({ quiet: true })

  if (loading) return <Loading what="this goal" />
  if (error) {
    return (
      <>
        <Feedback error={error} />
        <Link className="btn btn--secondary" to="/">
          Back to dashboard
        </Link>
      </>
    )
  }

  const { goal, progress, currency } = data
  const hasPlan = goal.steps.length > 0

  return (
    <>
      <div className="panel-header u-mb-md">
        <div>
          <h2 style={{ margin: 0 }}>{goal.name}</h2>
          <p className="muted" style={{ margin: '4px 0 0' }}>
            {money(goal.target_amount, currency)} by {longDate(goal.target_date)}
          </p>
        </div>
        <div className="btn-row">
          <PriorityBadge priority={goal.priority} />
          <span className={`badge badge--${goal.status}`}>{goal.status}</span>
          <Link className="btn btn--small btn--secondary" to={`/goals/${goal.goal_id}/edit`}>
            Edit goal
          </Link>
          <button type="button" className="btn btn--small btn--secondary" onClick={() => navigate('/')}>
            Back
          </button>
        </div>
      </div>

      <ProgressPanel progress={progress} currency={currency} />

      <AiModePanel goalId={goal.goal_id} currency={currency} hasPlan={hasPlan} onPlanned={refresh} />

      <section className="panel" aria-labelledby="plan-heading">
        <div className="panel-header">
          <h2 id="plan-heading">
            Savings plan <span className="muted">({goal.steps.length} steps)</span>
          </h2>
        </div>

        <div className="u-mt-md">
          <StepList goalId={goal.goal_id} steps={goal.steps} currency={currency} onChanged={refresh} />
        </div>
      </section>

      <section className="panel" aria-labelledby="contribute-heading">
        <h2 id="contribute-heading">Log a contribution</h2>
        <ContributionForm goalId={goal.goal_id} currency={currency} onRecorded={refresh} />
      </section>

      <section className="panel" aria-labelledby="history-heading">
        <h2 id="history-heading">
          Contributions <span className="muted">({goal.contribution_count})</span>
        </h2>
        {goal.contributions.length === 0 ? (
          <p className="empty-state">Nothing recorded yet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Date</th>
                <th scope="col">Notes</th>
                <th scope="col" className="numeric">
                  Amount
                </th>
              </tr>
            </thead>
            <tbody>
              {goal.contributions.map((item) => (
                <tr key={item.contribution_id}>
                  <td>{longDate(item.contribution_date)}</td>
                  <td>{item.notes || <span className="muted">--</span>}</td>
                  <td className="numeric">{money(item.amount, currency)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row" colSpan={2}>
                  Total saved
                </th>
                <td className="numeric">
                  <strong>{money(goal.saved_to_date, currency)}</strong>
                </td>
              </tr>
            </tfoot>
          </table>
        )}
      </section>
    </>
  )
}
