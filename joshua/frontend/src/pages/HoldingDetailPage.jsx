import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { deleteHolding, getAllocation, getHolding } from '../api'
import { useLoader } from '../hooks'
import { ErrorBanner, Loading } from '../components/Feedback'
import {
  changeClass,
  formatDate,
  formatMoney,
  formatPercent,
  formatSignedMoney,
  formatUnits,
} from '../format'

// The holding record itself carries no computed figures -- those live on
// /api/allocation, which the backend derives in Python. Both are fetched so
// the detail view can show stored fields and calculated ones together, and so
// a missing id still produces the backend's own 404 message.
async function loadHoldingDetail(id) {
  const [holding, allocation] = await Promise.all([getHolding(id), getAllocation()])
  const computed = allocation.holdings.find((item) => item.id === holding.id)
  return { ...holding, ...(computed || {}) }
}

export default function HoldingDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { status, data: holding, error, reload } = useLoader(() => loadHoldingDetail(id), [id])

  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState(null)

  async function handleDelete() {
    setDeleting(true)
    setDeleteError(null)
    try {
      await deleteHolding(id)
      navigate('/', { replace: true })
    } catch (failure) {
      setDeleteError(failure)
      setDeleting(false)
      setConfirming(false)
    }
  }

  return (
    <section className="page">
      <p className="breadcrumb">
        <Link to="/">&larr; Back to holdings</Link>
      </p>

      {status === 'loading' && <Loading label="Loading holding..." />}
      <ErrorBanner error={error} onRetry={reload} title="Could not load this holding" />

      {status === 'ready' && holding && (
        <>
          <header className="page-header">
            <div>
              <h2>
                {holding.ticker}
                <span className="page-subtitle">{holding.asset_name}</span>
              </h2>
              <p className="tag">{holding.asset_class}</p>
            </div>
            <div className="button-row">
              <Link to={`/holdings/${holding.id}/edit`} className="button button-primary">
                Edit
              </Link>
              <button
                type="button"
                className="button button-danger"
                onClick={() => setConfirming(true)}
                disabled={confirming || deleting}
              >
                Delete
              </button>
            </div>
          </header>

          <ErrorBanner error={deleteError} title="The holding could not be deleted" />

          {confirming && (
            <div className="banner banner-confirm" role="alertdialog" aria-label="Confirm delete">
              <h3 className="banner-title">Delete this holding?</h3>
              <p className="banner-message">
                {holding.ticker} -- {holding.asset_name} ({formatUnits(holding.units)} units,{' '}
                {formatMoney(holding.market_value)}) will be permanently removed. This cannot be
                undone.
              </p>
              <div className="button-row">
                <button
                  type="button"
                  className="button button-danger"
                  onClick={handleDelete}
                  disabled={deleting}
                >
                  {deleting ? 'Deleting...' : 'Yes, delete it'}
                </button>
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => setConfirming(false)}
                  disabled={deleting}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          <dl className="summary-tiles">
            <div className="summary-tile">
              <dt>Market value</dt>
              <dd>{formatMoney(holding.market_value)}</dd>
            </div>
            <div className="summary-tile">
              <dt>Cost basis</dt>
              <dd>{formatMoney(holding.cost_basis)}</dd>
            </div>
            <div className="summary-tile">
              <dt>Unrealised gain/loss</dt>
              <dd className={changeClass(holding.gain_loss)}>
                {formatSignedMoney(holding.gain_loss)}
                <span className="value-secondary">{formatPercent(holding.gain_loss_percent)}</span>
              </dd>
            </div>
          </dl>

          <h3 className="section-heading">Position details</h3>
          <dl className="detail-list">
            <div className="detail-row">
              <dt>Ticker</dt>
              <dd>{holding.ticker}</dd>
            </div>
            <div className="detail-row">
              <dt>Asset name</dt>
              <dd>{holding.asset_name}</dd>
            </div>
            <div className="detail-row">
              <dt>Asset class</dt>
              <dd>{holding.asset_class}</dd>
            </div>
            <div className="detail-row">
              <dt>Units</dt>
              <dd>{formatUnits(holding.units)}</dd>
            </div>
            <div className="detail-row">
              <dt>Average cost per unit</dt>
              <dd>{formatMoney(holding.average_cost)}</dd>
            </div>
            <div className="detail-row">
              <dt>Last price per unit</dt>
              <dd>{formatMoney(holding.last_price)}</dd>
            </div>
            <div className="detail-row">
              <dt>Currency</dt>
              <dd>{holding.currency}</dd>
            </div>
            <div className="detail-row">
              <dt>Price as at</dt>
              <dd>{formatDate(holding.price_as_at)}</dd>
            </div>
            <div className="detail-row">
              <dt>Purchase date</dt>
              <dd>{formatDate(holding.purchase_date)}</dd>
            </div>
            <div className="detail-row">
              <dt>Notes</dt>
              <dd>{holding.notes || '--'}</dd>
            </div>
          </dl>
        </>
      )}
    </section>
  )
}
