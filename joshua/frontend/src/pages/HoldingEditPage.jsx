import { Link, useNavigate, useParams } from 'react-router-dom'
import { getHolding, updateHolding } from '../api'
import { useLoader } from '../hooks'
import { ErrorBanner, Loading } from '../components/Feedback'
import HoldingForm from '../components/HoldingForm'

export default function HoldingEditPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { status, data: holding, error, reload } = useLoader(() => getHolding(id), [id])

  async function handleSubmit(payload) {
    await updateHolding(id, payload)
    navigate(`/holdings/${id}`, { replace: true })
  }

  return (
    <section className="page">
      <p className="breadcrumb">
        <Link to={`/holdings/${id}`}>&larr; Back to holding</Link>
      </p>
      <header className="page-header">
        <h2>Edit holding</h2>
      </header>

      {status === 'loading' && <Loading label="Loading holding..." />}
      <ErrorBanner error={error} onRetry={reload} title="Could not load this holding" />

      {status === 'ready' && holding && (
        <HoldingForm
          holding={holding}
          submitLabel="Save changes"
          onSubmit={handleSubmit}
          cancelTo={`/holdings/${id}`}
        />
      )}
    </section>
  )
}
