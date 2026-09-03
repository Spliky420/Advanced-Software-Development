import { useNavigate, useParams } from 'react-router-dom'
import * as api from '../api/client'
import GoalForm from '../components/GoalForm'
import { Feedback, Loading } from '../components/common'
import { useAction, useAsync } from '../hooks'

export default function GoalEditPage() {
  const { goalId } = useParams()
  const navigate = useNavigate()
  const { loading, data: goal, error } = useAsync(() => api.getGoal(goalId), [goalId])
  const { busy, error: saveError, run } = useAction()

  const submit = async (values) => {
    if (await run(() => api.updateGoal(goalId, values))) navigate(`/goals/${goalId}`)
  }

  if (loading) return <Loading what="this goal" />
  if (error) return <Feedback error={error} />

  return (
    <section className="panel" aria-labelledby="edit-goal-heading">
      <h2 id="edit-goal-heading">Edit &ldquo;{goal.name}&rdquo;</h2>
      <GoalForm
        initial={{
          name: goal.name,
          target_amount: String(goal.target_amount),
          target_date: goal.target_date,
          priority: goal.priority,
          status: goal.status,
        }}
        submitLabel="Save changes"
        busy={busy}
        serverError={saveError}
        onSubmit={submit}
        onCancel={() => navigate(`/goals/${goalId}`)}
      />
    </section>
  )
}
