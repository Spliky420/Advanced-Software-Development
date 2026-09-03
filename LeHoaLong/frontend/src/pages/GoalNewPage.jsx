import { useNavigate } from 'react-router-dom'
import * as api from '../api/client'
import GoalForm from '../components/GoalForm'
import { useAction } from '../hooks'
import { DEFAULT_USER_ID } from '../constants'

export default function GoalNewPage() {
  const navigate = useNavigate()
  const { busy, error, run } = useAction()

  const submit = async (values) => {
    const created = await run(() => api.createGoal({ ...values, user_id: DEFAULT_USER_ID }))
    // Straight to the detail page: the next thing anyone wants after creating
    // a goal is a plan for it, and that button lives there.
    if (created) navigate(`/goals/${created.goal_id}`)
  }

  return (
    <section className="panel" aria-labelledby="new-goal-heading">
      <h2 id="new-goal-heading">New goal</h2>
      <GoalForm
        submitLabel="Create goal"
        busy={busy}
        serverError={error}
        onSubmit={submit}
        onCancel={() => navigate('/')}
      />
    </section>
  )
}
