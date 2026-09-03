import { Link } from 'react-router-dom'
import { PriorityBadge, ProgressBar, StatusBadge } from './common'
import { longDate, money, signedMoney } from '../format'

// One goal on the dashboard.
//
// `progress` is the body of GET /api/goals/<id>/progress -- the OBSERVE phase.
// It may be null if that call failed, in which case the card still renders
// everything the list endpoint already provided; a broken status reading
// should not cost the user their goal.
export default function GoalCard({ goal, progress, currency, onDelete }) {
  const status = progress?.status
  const isInactive = goal.status !== 'active'

  return (
    <article className="goal-card">
      <div className="goal-card__head">
        <h3 className="goal-card__title">
          <Link to={`/goals/${goal.goal_id}`}>{goal.name}</Link>
        </h3>
        <div className="goal-card__badges">
          <PriorityBadge priority={goal.priority} />
          {isInactive ? <span className={`badge badge--${goal.status}`}>{goal.status}</span> : <StatusBadge status={status} />}
        </div>
      </div>

      <ProgressBar
        percentComplete={goal.percent_complete}
        status={status}
        savedLabel={`${money(goal.saved_to_date, currency)} saved`}
        targetLabel={money(goal.target_amount, currency)}
      />

      <div className="goal-card__meta">
        <span>Due {longDate(goal.target_date)}</span>
        <span>{money(goal.remaining_amount, currency)} to go</span>
      </div>

      {progress && (
        <div className="muted">
          {progress.has_plan ? (
            <>
              Plan expects {money(progress.required_to_date, currency)} by now &middot;{' '}
              {signedMoney(progress.variance, currency)}
            </>
          ) : (
            <>No plan yet &mdash; open the goal to generate one</>
          )}
        </div>
      )}

      <div className="goal-card__actions btn-row">
        <Link className="btn btn--small" to={`/goals/${goal.goal_id}`}>
          Open
        </Link>
        <Link className="btn btn--small btn--secondary" to={`/goals/${goal.goal_id}/edit`}>
          Edit
        </Link>
        <button type="button" className="btn btn--small btn--danger" onClick={() => onDelete(goal)}>
          Delete
        </button>
      </div>
    </article>
  )
}
