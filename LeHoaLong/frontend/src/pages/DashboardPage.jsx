import { useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import * as api from '../api/client'
import BudgetPanel from '../components/BudgetPanel'
import ConfirmDialog from '../components/ConfirmDialog'
import GoalCard from '../components/GoalCard'
import { Feedback, Loading } from '../components/common'
import { useAction, useAsync } from '../hooks'
import { DEFAULT_USER_ID } from '../constants'

// The goal dashboard: the budget panel, then every goal as a card.
//
// The on-track / behind / ahead reading on each card comes from
// GET /api/goals/<id>/progress -- the OBSERVE phase -- one call per card,
// fired together rather than in sequence. A card whose progress call fails
// still renders from the list data; a status badge is not worth losing the
// goal over.
async function loadDashboard(userId) {
  const [goalList, budget] = await Promise.all([
    api.listGoals({ user_id: userId }),
    api.getBudgetSummary(userId),
  ])
  const progress = await Promise.all(
    goalList.goals.map((goal) => api.getProgress(goal.goal_id).catch(() => null)),
  )
  return {
    goals: goalList.goals.map((goal, index) => ({ goal, progress: progress[index] })),
    budget,
  }
}

export default function DashboardPage() {
  const userId = DEFAULT_USER_ID
  const { loading, data, error, reload } = useAsync(() => loadDashboard(userId), [userId])
  const [pendingDelete, setPendingDelete] = useState(null)
  const { busy: deleting, error: deleteError, run } = useAction()

  const confirmDelete = useCallback(async () => {
    if (await run(() => api.deleteGoal(pendingDelete.goal_id).then(() => true))) {
      setPendingDelete(null)
      reload({ quiet: true })
    }
  }, [pendingDelete, run, reload])

  if (loading) return <Loading what="your goals" />
  if (error) return <Feedback error={error} />

  const { goals, budget } = data
  const currency = budget.currency

  return (
    <>
      <Feedback error={deleteError} />

      <BudgetPanel summary={budget} userId={userId} onSaved={() => reload({ quiet: true })} />

      <section aria-labelledby="goals-heading">
        <div className="panel-header u-mb-md">
          <h2 id="goals-heading">
            Goals <span className="muted">({goals.length})</span>
          </h2>
          <Link className="btn" to="/goals/new">
            New goal
          </Link>
        </div>

        {goals.length === 0 ? (
          <p className="empty-state">
            No goals yet. <Link to="/goals/new">Create your first one</Link> and the assistant will build a
            savings plan for it.
          </p>
        ) : (
          <div className="goal-grid">
            {goals.map(({ goal, progress }) => (
              <GoalCard
                key={goal.goal_id}
                goal={goal}
                progress={progress}
                currency={currency}
                onDelete={setPendingDelete}
              />
            ))}
          </div>
        )}
      </section>

      {pendingDelete && (
        <ConfirmDialog
          title={`Delete "${pendingDelete.name}"?`}
          message={
            <p>
              This removes the goal, its whole savings plan and every contribution recorded against it. It
              cannot be undone.
            </p>
          }
          busy={deleting}
          onConfirm={confirmDelete}
          onCancel={() => setPendingDelete(null)}
        />
      )}
    </>
  )
}
