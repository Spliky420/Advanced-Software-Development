import { useState } from 'react'
import { runDriftReview } from '../api'
import { AiLoading, EmptyState, ErrorBanner } from '../components/Feedback'
import {
  driftClass,
  formatMoney,
  formatPercent,
  formatPercentagePoints,
  formatThresholdPoints,
} from '../format'

// The four phases of the agentic loop, in order. Each one is rendered as its
// own labelled section so the Plan -> Act -> Observe -> Adapt cycle is visible
// in the UI rather than only in the backend.
const PHASES = [
  { key: 'plan', step: 1, title: 'Plan', tagline: 'Decide what to examine' },
  { key: 'act', step: 2, title: 'Act', tagline: 'Compute the actual drift' },
  { key: 'observe', step: 3, title: 'Observe', tagline: 'Classify what breached the threshold' },
  { key: 'adapt', step: 4, title: 'Adapt', tagline: 'Explain the result in plain English' },
]

function PhaseSection({ phase, children }) {
  return (
    <section className={`phase phase-${phase.key}`} aria-labelledby={`phase-${phase.key}`}>
      <header className="phase-header">
        <span className="phase-step" aria-hidden="true">
          {phase.step}
        </span>
        <div>
          <h3 id={`phase-${phase.key}`} className="phase-title">
            <span className="phase-label">Phase {phase.step}</span>
            {phase.title}
          </h3>
          <p className="phase-tagline">{phase.tagline}</p>
        </div>
      </header>
      <div className="phase-body">{children}</div>
    </section>
  )
}

function directionLabel(direction) {
  if (direction === 'overweight') return 'Overweight'
  if (direction === 'underweight') return 'Underweight'
  return 'On target'
}

function DriftTable({ rows, showDirection = false }) {
  if (!rows || rows.length === 0) {
    return <EmptyState>None.</EmptyState>
  }
  return (
    <div className="table-scroll">
      <table className="data-table drift-table">
        <thead>
          <tr>
            <th scope="col">Asset class</th>
            <th scope="col" className="numeric">Target</th>
            <th scope="col" className="numeric">Actual</th>
            <th scope="col" className="numeric">Market value</th>
            <th scope="col" className="numeric">Drift</th>
            {showDirection && <th scope="col">Direction</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.asset_class}>
              <th scope="row">{row.asset_class}</th>
              <td className="numeric">{formatPercent(row.target_percent)}</td>
              <td className="numeric">{formatPercent(row.actual_percent)}</td>
              <td className="numeric">{formatMoney(row.market_value)}</td>
              <td className={`numeric ${driftClass(row.drift_percentage_points)}`}>
                {formatPercentagePoints(row.drift_percentage_points)}
              </td>
              {showDirection && (
                <td>
                  <span className={`direction direction-${row.direction}`}>
                    {directionLabel(row.direction)}
                  </span>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function DriftReviewPage() {
  const [review, setReview] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  async function run() {
    setLoading(true)
    setError(null)
    try {
      setReview(await runDriftReview())
    } catch (failure) {
      setError(failure)
      setReview(null)
    } finally {
      setLoading(false)
    }
  }

  const phaseByKey = Object.fromEntries(PHASES.map((phase) => [phase.key, phase]))

  return (
    <section className="page">
      <header className="page-header">
        <h2>Drift review</h2>
        <button type="button" className="button button-primary" onClick={run} disabled={loading}>
          {loading ? 'Running...' : review ? 'Run drift review again' : 'Run drift review'}
        </button>
      </header>

      <p className="page-intro">
        The drift review runs a Plan &rarr; Act &rarr; Observe &rarr; Adapt loop. The first three
        phases are deterministic Python; only Adapt calls the model, and only about breaches
        Observe has already found.
      </p>

      {loading && <AiLoading label="Running the drift review..." />}
      <ErrorBanner error={error} title="The drift review could not be run" />

      {!review && !loading && !error && (
        <EmptyState>Run the review to see all four phases of the loop.</EmptyState>
      )}

      {review && !loading && (
        <div className="phase-list">
          <PhaseSection phase={phaseByKey.plan}>
            <p className="phase-description">{review.plan.description}</p>
            <dl className="phase-facts">
              <div>
                <dt>Drift threshold</dt>
                <dd>{formatThresholdPoints(review.plan.threshold_percent)}</dd>
              </div>
              <div>
                <dt>Asset classes to examine</dt>
                <dd>{review.plan.asset_classes_to_examine.length}</dd>
              </div>
            </dl>
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Asset class</th>
                    <th scope="col" className="numeric">Target</th>
                  </tr>
                </thead>
                <tbody>
                  {review.plan.asset_classes_to_examine.map((assetClass) => (
                    <tr key={assetClass}>
                      <th scope="row">{assetClass}</th>
                      <td className="numeric">
                        {formatPercent(review.plan.target_percent_by_class[assetClass])}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </PhaseSection>

          <PhaseSection phase={phaseByKey.act}>
            <p className="phase-description">{review.act.description}</p>
            <dl className="phase-facts">
              <div>
                <dt>Total market value</dt>
                <dd>{formatMoney(review.act.total_market_value)}</dd>
              </div>
              <div>
                <dt>Classes measured</dt>
                <dd>{review.act.drift_by_class.length}</dd>
              </div>
            </dl>
            <DriftTable rows={review.act.drift_by_class} />
          </PhaseSection>

          <PhaseSection phase={phaseByKey.observe}>
            <p className="phase-description">{review.observe.description}</p>
            <dl className="phase-facts">
              <div>
                <dt>Threshold</dt>
                <dd>{formatThresholdPoints(review.observe.threshold_percent)}</dd>
              </div>
              <div>
                <dt>Breaches</dt>
                <dd>{review.observe.breach_count}</dd>
              </div>
              <div>
                <dt>Within threshold</dt>
                <dd>{review.observe.within_threshold.length}</dd>
              </div>
            </dl>

            <h4 className="phase-subheading">Breaching the threshold</h4>
            <DriftTable rows={review.observe.breaches} showDirection />

            <h4 className="phase-subheading">Within the threshold</h4>
            <DriftTable rows={review.observe.within_threshold} />
          </PhaseSection>

          <PhaseSection phase={phaseByKey.adapt}>
            <p className="phase-description">{review.adapt.description}</p>
            <dl className="phase-facts">
              <div>
                <dt>Model called</dt>
                <dd>{review.adapt.llm_called ? 'Yes' : 'No -- nothing breached'}</dd>
              </div>
              <div>
                <dt>Model</dt>
                <dd>{review.adapt.model_name ? <code>{review.adapt.model_name}</code> : '--'}</dd>
              </div>
            </dl>
            <article className="ai-result">
              <p className="ai-text">{review.adapt.summary}</p>
              {review.insight_log_id != null && (
                <footer className="ai-meta">Logged to insight_log #{review.insight_log_id}</footer>
              )}
            </article>
          </PhaseSection>
        </div>
      )}
    </section>
  )
}
