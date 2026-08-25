import { Link, useNavigate } from 'react-router-dom'
import { createHolding } from '../api'
import HoldingForm from '../components/HoldingForm'

export default function HoldingNewPage() {
  const navigate = useNavigate()

  async function handleSubmit(payload) {
    const created = await createHolding(payload)
    navigate(`/holdings/${created.id}`, { replace: true })
  }

  return (
    <section className="page">
      <p className="breadcrumb">
        <Link to="/">&larr; Back to holdings</Link>
      </p>
      <header className="page-header">
        <h2>Add a holding</h2>
      </header>
      <HoldingForm submitLabel="Add holding" onSubmit={handleSubmit} cancelTo="/" />
    </section>
  )
}
