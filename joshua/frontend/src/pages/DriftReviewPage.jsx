import { useState } from 'react'
import { runDriftReview } from '../api'
import { AiLoading, EmptyState, ErrorBanner, WarningBanner } from '../components/Feedback'
import {
  driftClass,
  formatMoney,
  formatPercent,
  formatPercentagePoints,
  formatThresholdPoints,
} from '../format'

// The phases of the agentic loop, in order. Each one is rendered as its own
// labelled section so the Plan -> Act -> Observe -> Context -> Adapt cycle is
// visible in the UI rather than only in the backend.
const PHASES = [
  { key: 'plan', step: 1, title: 'Plan', tagline: 'Decide what to examine' },
  { key: 'act', step: 2, title: 'Act', tagline: 'Compute the actual drift' },
  { key: 'observe', step: 3, title: 'Observe', tagline: 'Classify what breached the threshold' },
  { key: 'context', step: 4, title: 'Context', tagline: 'Fetch reference material for the wording' },
  { key: 'adapt', step: 5, title: 'Adapt', tagline: 'Explain the result in plain English' },
]

const STATUS_LABELS = {
  found: 'Found',
  insufficient_context: 'No relevant context',
  unavailable: 'Unavailable',
  disabled: 'Disabled',
}

// Why a source was unavailable -- kept distinct from "no relevant context",
// which means the server answered but had nothing about these asset classes.
const FAILURE_LABELS = {
  unreachable: 'Server unreachable',
  timeout: 'Timed out',
  error: 'Server error',
}

function StatusPill({ status, failure }) {
  const label = status === 'unavailable' && FAILURE_LABELS[failure]
    ? FAILURE_LABELS[failure]
    : STATUS_LABELS[status] ?? status
  return <span className={`status status-${status}`}>{label}</span>
}

function InsufficientContextBanner({ reason, children }) {
  return (
    <div className="banner banner-insufficient" role="status">
      <strong className="banner-title">Insufficient context</strong>
      <p className="banner-message">{reason}</p>
      {children}
    </div>
  )
}

const SUMMARY_SOURCES = {
  model: { label: 'Model', note: 'Written by the model; every figure passed the check.' },
  fallback: { label: 'Python fallback', note: 'Model text rejected; summary built in Python.' },
  no_breaches: { label: 'Python', note: 'Nothing breached, so the model was not called.' },
}

function SummarySourcePill({ source }) {
  const known = SUMMARY_SOURCES[source]
  return (
    <span className={`summary-source summary-source-${source}`}>{known ? known.label : source}</span>
  )
}

// Figures arrive as JSON numbers (1993.0 -> 1993); show them as plain text,
// not as money or percentages -- they are exactly what the check rejected.
function formatRejected(figures) {
  return figures.map((value) => String(value)).join(', ')
}

function citationLabel(citation) {
  if (citation.kind === 'rag') {
    return `${citation.source_id ?? '?'}#${citation.chunk_id ?? '?'}`
  }
  return citation.term
}

function GlossaryList({ entries }) {
  if (!entries || entries.length === 0) {
    return <EmptyState>No glossary lookups.</EmptyState>
  }
  return (
    <ul className="context-list">
      {entries.map((entry) => (
        <li key={entry.term} className="context-item">
          <div className="context-item-header">
            <strong>{entry.term}</strong>
            <StatusPill status={entry.status} />
            <span className="context-item-meta">for {entry.asset_classes.join(', ')}</span>
          </div>
          {entry.status === 'found' ? (
            <p className="context-text">{entry.definition}</p>
          ) : (
            <p className="context-error">{entry.error}</p>
          )}
          <p className="context-item-meta">
            Source: <code>{entry.source}</code>
          </p>
        </li>
      ))}
    </ul>
  )
}

function RetrievalSection({ retrieval }) {
  if (!retrieval) {
    return <EmptyState>The RAG server was not called.</EmptyState>
  }
  return (
    <>
      <dl className="phase-facts">
        <div>
          <dt>Query</dt>
          <dd>
            <code>{retrieval.query}</code>
          </dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>
            <StatusPill status={retrieval.status} failure={retrieval.failure} />
          </dd>
        </div>
        <div>
          <dt>Relevant passages</dt>
          <dd>{retrieval.chunks.length}</dd>
        </div>
        {retrieval.dropped?.length > 0 && (
          <div>
            <dt>Dropped as off-topic</dt>
            <dd>{retrieval.dropped.length}</dd>
          </div>
        )}
      </dl>
      {retrieval.status === 'unavailable' && <p className="context-error">{retrieval.error}</p>}
      {retrieval.status === 'insufficient_context' && (
        <p className="context-item-meta">
          The RAG server answered, but nothing it returned mentions the breached asset classes,
          so no passage was sent to the model.
        </p>
      )}
      {retrieval.dropped?.length > 0 && (
        <p className="context-item-meta">
          Dropped:{' '}
          {retrieval.dropped.map((chunk, index) => (
            <span key={`${chunk.chunk_id}-${index}`}>
              {index > 0 && ', '}
              <code>{citationLabel({ kind: 'rag', ...chunk })}</code>
            </span>
          ))}
        </p>
      )}
      {retrieval.chunks.length > 0 && (
        <div className="table-scroll">
          {/* Server order, as returned. Distance is shown raw: its meaning
              (and whether lower is better) belongs to the RAG server. */}
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col" className="numeric">Rank</th>
                <th scope="col">Source</th>
                <th scope="col" className="numeric">Distance (as returned)</th>
                <th scope="col">Passage</th>
              </tr>
            </thead>
            <tbody>
              {retrieval.chunks.map((chunk, index) => (
                <tr key={`${chunk.chunk_id}-${index}`}>
                  <td className="numeric">{chunk.rank ?? index + 1}</td>
                  <td>
                    <code>{citationLabel({ kind: 'rag', ...chunk })}</code>
                  </td>
                  <td className="numeric">{chunk.distance ?? '--'}</td>
                  <td className="context-text">{chunk.text}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

function CitationList({ citations, summarySource }) {
  if (!citations || citations.length === 0) {
    return (
      <p className="ai-meta">
        {summarySource === 'fallback'
          ? 'No sources cited: a rejected summary cites nothing.'
          : 'No reference material was used.'}
      </p>
    )
  }
  return (
    <ol className="citation-list">
      {citations.map((citation, index) => (
        <li key={`${citation.kind}-${citationLabel(citation)}-${index}`}>
          <span className="citation-kind">{citation.kind === 'rag' ? 'RAG passage' : 'Glossary'}</span>{' '}
          <code>{citationLabel(citation)}</code>
          {citation.kind === 'rag' && citation.distance != null && (
            <span className="context-item-meta"> distance {citation.distance}</span>
          )}
          {citation.kind === 'glossary' && (
            <span className="context-item-meta"> via {citation.source}</span>
          )}
        </li>
      ))}
    </ol>
  )
}

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
        The drift review runs a Plan &rarr; Act &rarr; Observe &rarr; Context &rarr; Adapt loop.
        Plan, Act and Observe are deterministic Python. Context fetches reference material from
        the shared MCP and RAG servers. Only Adapt calls the model, and only about breaches
        Observe has already found. Its text is checked, and rejected if it contains any figure
        that was not supplied.
      </p>

      {loading && <AiLoading label="Running the drift review..." />}
      <ErrorBanner error={error} title="The drift review could not be run" />

      {!review && !loading && !error && (
        <EmptyState>Run the review to see every phase of the loop.</EmptyState>
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

          {review.context && (
            <PhaseSection phase={phaseByKey.context}>
              <p className="phase-description">{review.context.description}</p>
              <dl className="phase-facts">
                <div>
                  <dt>MCP glossary called</dt>
                  <dd>{review.context.mcp_called ? 'Yes' : 'No'}</dd>
                </div>
                <div>
                  <dt>RAG server called</dt>
                  <dd>{review.context.rag_called ? 'Yes' : 'No'}</dd>
                </div>
                {review.context.reason && (
                  <div>
                    <dt>Note</dt>
                    <dd>{review.context.reason}</dd>
                  </div>
                )}
              </dl>
              {review.context.insufficient_context ? (
                <InsufficientContextBanner reason={review.context.insufficient_reason} />
              ) : (
                <p className="ai-meta">
                  Reference material goes to the model for wording only. Portfolio figures are
                  supplied separately and must be used verbatim.
                </p>
              )}

              <h4 className="phase-subheading">Glossary definitions (MCP)</h4>
              <GlossaryList entries={review.context.glossary} />

              <h4 className="phase-subheading">Retrieved passages (RAG)</h4>
              <RetrievalSection retrieval={review.context.retrieval} />
            </PhaseSection>
          )}

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
              {review.adapt.summary_source && (
                <div>
                  <dt>Summary source</dt>
                  <dd>
                    <SummarySourcePill source={review.adapt.summary_source} />
                  </dd>
                </div>
              )}
              {review.adapt.context_status && (
                <div>
                  <dt>Context</dt>
                  <dd>
                    <span className={`context-status context-status-${review.adapt.context_status}`}>
                      {review.adapt.context_status === 'grounded' ? 'Grounded' : 'Insufficient'}
                    </span>
                  </dd>
                </div>
              )}
            </dl>

            {review.adapt.context_status === 'insufficient_context' && (
              <InsufficientContextBanner reason={review.context?.insufficient_reason}>
                <p className="banner-hint">
                  The model was told no reference material exists and to state the
                  Python-computed figures only -- no explanation, background or sources.
                </p>
              </InsufficientContextBanner>
            )}

            {review.adapt.summary_source === 'fallback' && (
              <WarningBanner>
                <strong className="banner-title">Model summary rejected -- Python fallback shown</strong>
                {review.adapt.unsupplied_figures?.length > 0 && (
                  <p className="banner-message">
                    The model&rsquo;s text contained{' '}
                    {review.adapt.unsupplied_figures.length === 1 ? 'a figure' : 'figures'} that
                    were not in the portfolio figures it was given:{' '}
                    <strong className="rejected-figures">
                      {formatRejected(review.adapt.unsupplied_figures)}
                    </strong>
                    .
                  </p>
                )}
                {review.adapt.misattributed?.length > 0 && (
                  <>
                    <p className="banner-message">
                      The model attached real figures or directions to the wrong asset class:
                    </p>
                    <ul className="banner-list">
                      {review.adapt.misattributed.map((problem, index) => (
                        <li key={index}>
                          {problem.asset_class}:{' '}
                          {problem.figure != null ? (
                            <>
                              <strong className="rejected-figures">{String(problem.figure)}</strong>{' '}
                              is not one of its figures
                            </>
                          ) : (
                            <>
                              called <strong>{problem.direction}</strong>, which it is not
                            </>
                          )}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
                <p className="banner-message">
                  The summary below was built in Python from the same figures, so every number in
                  it comes from allocation.py.
                </p>
                <p className="banner-hint">
                  The model&rsquo;s original text is kept in the insight log.
                </p>
              </WarningBanner>
            )}

            <article
              className={`ai-result${review.adapt.summary_source === 'fallback' ? ' ai-result-fallback' : ''}`}
            >
              {review.adapt.summary_source && (
                <p className="ai-result-label">
                  {SUMMARY_SOURCES[review.adapt.summary_source]?.note}
                </p>
              )}
              <p className="ai-text">{review.adapt.summary}</p>
              {review.insight_log_id != null && (
                <footer className="ai-meta">Logged to insight_log #{review.insight_log_id}</footer>
              )}
            </article>

            {review.adapt.llm_called && (
              <>
                <h4 className="phase-subheading">Sources</h4>
                <CitationList
                  citations={review.adapt.citations}
                  summarySource={review.adapt.summary_source}
                />
              </>
            )}
          </PhaseSection>
        </div>
      )}
    </section>
  )
}
