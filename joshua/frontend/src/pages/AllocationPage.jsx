import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { createInsight, getAllocation, getTargets } from '../api'
import { useLoader } from '../hooks'
import { AiLoading, ErrorBanner, Loading } from '../components/Feedback'
import {
  changeClass,
  driftClass,
  formatMoney,
  formatPercent,
  formatPercentagePoints,
  formatSignedMoney,
} from '../format'

async function loadAllocation() {
  const [allocation, targets] = await Promise.all([getAllocation(), getTargets()])
  return { allocation, targets }
}

// Cover the union of "has a target" and "is actually held", the same way the
// backend's ACT phase does: a class held with no target is real drift, and a
// target with nothing held against it is real drift too. Showing only one side
// would hide half of it.
function buildRows(allocation, targets) {
  const actualByClass = new Map(
    allocation.portfolio.asset_class_allocation.map((item) => [item.asset_class, item]),
  )
  const targetByClass = new Map(targets.map((item) => [item.asset_class, item.target_percent]))

  const assetClasses = [...new Set([...targetByClass.keys(), ...actualByClass.keys()])].sort()

  return assetClasses.map((assetClass) => {
    const actual = actualByClass.get(assetClass)
    const actualPercent = actual ? actual.percent_of_total : 0
    const targetPercent = targetByClass.get(assetClass) ?? 0
    return {
      assetClass,
      marketValue: actual ? actual.market_value : 0,
      actualPercent,
      targetPercent,
      // Percentage points, not percent -- actual minus target.
      difference: actualPercent - targetPercent,
      hasTarget: targetByClass.has(assetClass),
      isHeld: Boolean(actual),
    }
  })
}

export default function AllocationPage() {
  const { status, data, error, reload } = useLoader(loadAllocation, [])

  const [insight, setInsight] = useState(null)
  const [insightError, setInsightError] = useState(null)
  const [insightLoading, setInsightLoading] = useState(false)

  const rows = useMemo(
    () => (data ? buildRows(data.allocation, data.targets) : []),
    [data],
  )

  async function requestSummary() {
    setInsightLoading(true)
    setInsightError(null)
    try {
      setInsight(await createInsight())
    } catch (failure) {
      setInsightError(failure)
      setInsight(null)
    } finally {
      setInsightLoading(false)
    }
  }

  const portfolio = data ? data.allocation.portfolio : null

  return (
    <section className="page">
      <header className="page-header">
        <h2>Allocation vs target</h2>
        <Link to="/targets" className="button button-secondary">
          Edit targets
        </Link>
      </header>

      {status === 'loading' && <Loading label="Loading allocation..." />}
      <ErrorBanner error={error} onRetry={reload} title="Could not load the allocation" />

      {status === 'ready' && portfolio && (
        <>
          <dl className="summary-tiles">
            <div className="summary-tile">
              <dt>Total market value</dt>
              <dd>{formatMoney(portfolio.total_market_value)}</dd>
            </div>
            <div className="summary-tile">
              <dt>Total cost</dt>
              <dd>{formatMoney(portfolio.total_cost)}</dd>
            </div>
            <div className="summary-tile">
              <dt>Total unrealised gain/loss</dt>
              <dd className={changeClass(portfolio.total_gain_loss)}>
                {formatSignedMoney(portfolio.total_gain_loss)}
              </dd>
            </div>
          </dl>

          <div className="table-scroll">
            <table className="data-table allocation-table">
              <caption className="table-caption">
                Difference is actual minus target, in percentage points. Positive is overweight,
                negative is underweight.
              </caption>
              <thead>
                <tr>
                  <th scope="col">Asset class</th>
                  <th scope="col" className="numeric">Market value</th>
                  <th scope="col" className="numeric">Actual</th>
                  <th scope="col" className="numeric">Target</th>
                  <th scope="col" className="numeric">Difference</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.assetClass}>
                    <th scope="row">
                      {row.assetClass}
                      {!row.hasTarget && <span className="row-note">no target set</span>}
                      {!row.isHeld && <span className="row-note">nothing held</span>}
                    </th>
                    <td className="numeric">{formatMoney(row.marketValue)}</td>
                    <td className="numeric">{formatPercent(row.actualPercent)}</td>
                    <td className="numeric">{formatPercent(row.targetPercent)}</td>
                    <td className={`numeric ${driftClass(row.difference)}`}>
                      {formatPercentagePoints(row.difference)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <section className="ai-panel">
            <header className="page-header">
              <h3>AI portfolio summary</h3>
              <button
                type="button"
                className="button button-primary"
                onClick={requestSummary}
                disabled={insightLoading}
              >
                {insightLoading ? 'Generating...' : insight ? 'Regenerate summary' : 'Generate summary'}
              </button>
            </header>

            <p className="ai-note">
              The figures above are calculated by the backend in Python and handed to the model as
              finished values. The model only writes commentary around them.
            </p>

            {insightLoading && <AiLoading label="Asking the model for a summary..." />}
            <ErrorBanner error={insightError} title="The summary could not be generated" />

            {insight && !insightLoading && (
              <article className="ai-result">
                <p className="ai-text">{insight.response_text}</p>
                <footer className="ai-meta">
                  Generated by <code>{insight.model_name}</code> at {insight.created_at}
                </footer>
              </article>
            )}
          </section>
        </>
      )}
    </section>
  )
}
