// The grounded answer panel: a question, the answer, its confidence, and the
// sources it was grounded in.
//
// Three rules this component follows, all of them marking requirements:
//
//   * the confidence badge and the citation list are visible without
//     expanding anything. Only the chunk *text* is behind a disclosure,
//     because that is bulk rather than attribution.
//   * the confidence category and the citations are rendered exactly as the
//     RAG server returned them. The badge colour is chosen from the category,
//     but the category itself is never recomputed or relabelled -- an
//     unrecognised value is displayed as-is rather than mapped onto something
//     this component expected.
//   * "Insufficient evidence." is rendered as the correct answer it is, not as
//     an error. A grounded feature admitting it has no evidence is behaving
//     properly.

import { useState } from 'react'
import { BusyButton, Feedback } from './common'
import { money, signedMoney } from '../format'

// Known categories get a colour; anything else still renders, uncoloured.
const CONFIDENCE_CLASS = {
  high: 'confidence--high',
  medium: 'confidence--medium',
  low: 'confidence--low',
}

function ConfidenceBadge({ category }) {
  if (category === null || category === undefined || category === '') {
    return <span className="badge confidence confidence--unknown">confidence not reported</span>
  }
  const tone = CONFIDENCE_CLASS[String(category).toLowerCase()] || 'confidence--unknown'
  return (
    <span className={`badge confidence ${tone}`} title="Reported by the RAG server, not recalculated here">
      {category} confidence
    </span>
  )
}

function Citations({ citations, chunks }) {
  const [open, setOpen] = useState(false)
  const textFor = (chunkId) => chunks?.find((chunk) => chunk.chunk_id === chunkId)?.text

  if (citations.length === 0) {
    return (
      <p className="muted">
        The server returned no citations for this answer.
      </p>
    )
  }

  return (
    <div className="citations">
      <div className="citations__header">
        <h4 className="citations__heading">
          Sources <span className="muted">({citations.length})</span>
        </h4>
        <button
          type="button"
          className="btn btn--small btn--secondary"
          onClick={() => setOpen((shown) => !shown)}
          aria-expanded={open}
        >
          {open ? 'Hide' : 'Show'} the retrieved text
        </button>
      </div>

      {/* Visible without expanding: every source_id and chunk_id. */}
      <ol className="citations__list">
        {citations.map((citation, index) => (
          <li key={`${citation.chunk_id}-${index}`}>
            <span className="citations__source">{citation.source_id}</span>
            <code className="citations__chunk">{citation.chunk_id}</code>
            {open && (
              <blockquote className="citations__text">
                {textFor(citation.chunk_id) || <span className="muted">text not retrieved</span>}
              </blockquote>
            )}
          </li>
        ))}
      </ol>
    </div>
  )
}

function WithheldAnswer({ answer, relevance }) {
  // The retrieved text was not about the question, so the model's reply could
  // only have come from outside the corpus. It is kept, behind a toggle, so
  // the decision can be checked rather than taken on trust.
  const [shown, setShown] = useState(false)
  const missing = relevance?.missing_terms || []
  const total = relevance?.question_terms?.length ?? 0
  const matched = relevance?.matched_terms?.length ?? 0

  return (
    <div className="callout callout--warning">
      <strong>Insufficient evidence.</strong>
      <div className="u-mt-sm">
        The retrieved sources are not about this question: {matched} of {total} of its key words
        appear in them
        {missing.length > 0 && <> (not found: {missing.join(', ')})</>}. The model replied anyway,
        but that reply could not have come from the corpus, so it is not shown as an answer.
      </div>
      <button
        type="button"
        className="btn btn--small btn--secondary u-mt-sm"
        onClick={() => setShown((open) => !open)}
        aria-expanded={shown}
      >
        {shown ? 'Hide' : 'Show'} the model&apos;s ungrounded reply
      </button>
      {shown && <blockquote className="citations__text">{answer}</blockquote>}
    </div>
  )
}

function Situation({ situation, currency }) {
  // Stated by this feature, from its own Python figures, so the panel does not
  // depend on the model's prose repeating them correctly.
  return (
    <div className="budget-figures grounded__situation">
      <div>
        <span className="figure__label">Saved so far</span>
        <span className="figure__value">{money(situation.saved_to_date, currency)}</span>
      </div>
      <div>
        <span className="figure__label">The plan expected by now</span>
        <span className="figure__value">{money(situation.required_to_date, currency)}</span>
      </div>
      <div>
        <span className="figure__label">Difference</span>
        <span className="figure__value">{signedMoney(situation.variance, currency)}</span>
      </div>
      <div>
        <span className="figure__label">Still to save</span>
        <span className="figure__value">{money(situation.remaining_amount, currency)}</span>
      </div>
    </div>
  )
}

export default function GroundedAnswerPanel({
  result,
  busy,
  error,
  currency,
  onExplain,
  onAsk,
  suggestions = [],
}) {
  const [question, setQuestion] = useState('')

  const submit = (event) => {
    event.preventDefault()
    const trimmed = question.trim()
    if (trimmed) onAsk(trimmed)
  }

  return (
    <div className="grounded">
      <p className="muted">
        Answers come from the shared RAG server: your question is matched against the team&apos;s
        knowledge corpus, and only the retrieved text is used to answer it. Every answer below
        carries the sources it was grounded in.
      </p>

      <div className="btn-row">
        <BusyButton busy={busy} busyLabel="Retrieving and answering..." onClick={onExplain}>
          Explain this goal
        </BusyButton>
      </div>

      <form onSubmit={submit} className="grounded__form">
        <label htmlFor="rag-question">Or ask a question of your own</label>
        <div className="grounded__row">
          <input
            id="rag-question"
            type="text"
            maxLength={500}
            placeholder="What is an emergency fund?"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            disabled={busy}
          />
          <BusyButton busy={busy} busyLabel="Working..." disabled={!question.trim()} onClick={submit}>
            Ask
          </BusyButton>
        </div>
        {suggestions.length > 0 && (
          <div className="grounded__suggestions">
            <span className="muted">Try:</span>
            {suggestions.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                className="btn btn--small btn--secondary"
                disabled={busy}
                onClick={() => {
                  setQuestion(suggestion)
                  onAsk(suggestion)
                }}
              >
                {suggestion}
              </button>
            ))}
          </div>
        )}
      </form>

      {busy && (
        <p className="muted u-mt-sm" role="status">
          Retrieving from the corpus, then asking the local model to answer from it. This runs on a
          local model and can take a while on the first question after startup.
        </p>
      )}

      <Feedback error={error} />

      {result && !busy && (
        <div className="grounded__answer u-mt-md">
          <div className="grounded__answer-header">
            <h4 className="grounded__heading">Grounded answer</h4>
            <ConfidenceBadge category={result.confidence_category} />
          </div>

          <p className="grounded__question muted">{result.question}</p>

          {result.insufficient_evidence ? (
            <div className="callout callout--warning">
              <strong>{result.answer}</strong>
              <div className="u-mt-sm">
                The corpus did not contain enough evidence to answer this, and the assistant said so
                rather than answering from outside it. The sources it searched are listed below.
              </div>
            </div>
          ) : result.answer_withheld ? (
            <WithheldAnswer answer={result.answer} relevance={result.relevance} />
          ) : (
            <p className="grounded__text">{result.answer}</p>
          )}

          {result.situation && <Situation situation={result.situation} currency={currency} />}
          {result.situation && (
            <p className="muted grounded__note">
              The figures above are this feature&apos;s own, computed in Python. The answer is the
              model&apos;s wording of the retrieved text.
            </p>
          )}

          <Citations citations={result.citations || []} chunks={result.retrieved_chunks} />

          <p className="muted grounded__meta">
            {result.retrieval_summary?.retrieved_count ?? 0} of {result.k} requested chunks retrieved
            {result.duration_ms ? ` in ${(result.duration_ms / 1000).toFixed(1)}s` : ''}
            {result.chunks_match_citations === false &&
              ' · the retrieved text and the citations did not match, so the corpus may have changed mid-request'}
          </p>
        </div>
      )}
    </div>
  )
}
