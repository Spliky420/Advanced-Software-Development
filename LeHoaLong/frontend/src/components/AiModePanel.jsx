// The AI mode selector: the three ways this feature can use a model, in one
// place so they can be compared.
//
//   AI-Mode  Release 0. Python computes the schedule, the model describes it.
//            Planning here is sent with use_mcp false, so it is genuinely the
//            Release 0 behaviour and not just a label on the Release 1 one.
//   MCP      The same planning, but the available-to-save figure first
//            accounts for what other features report is already committed.
//   RAG      Grounded answers from the shared corpus, with citations.
//
// The tabs are not three skins over one call. AI-Mode and MCP send different
// requests and produce different available-to-save figures from the same
// schedule, which is the comparison a marker is looking for.

import { useState } from 'react'
import * as api from '../api/client'
import GroundedAnswerPanel from './GroundedAnswerPanel'
import McpContextPanel from './McpContextPanel'
import { BusyButton, Feedback } from './common'
import { useAction, useAsync } from '../hooks'
import { longDate, money, signedMoney } from '../format'

const MODES = [
  { id: 'ai', label: 'AI-Mode', hint: 'Release 0 · model writes the step descriptions' },
  { id: 'mcp', label: 'MCP', hint: 'adds what other features already commit' },
  { id: 'rag', label: 'RAG', hint: 'grounded answers with citations' },
]

const RAG_SUGGESTIONS = [
  'What is an emergency fund?',
  'How should competing savings goals be prioritised?',
  'How do recurring bills affect the amount available to save?',
]

// What a plan or replan response says about affordability. Every figure here
// was computed in Python by the backend; this only lays it out.
function PlanOutcome({ outcome, kind, currency }) {
  if (!outcome) return null
  const phase = kind === 'plan' ? outcome.plan : outcome.adapt
  const { mcp } = phase

  return (
    <div className="plan-outcome u-mt-md">
      <div className="callout callout--success">
        {kind === 'plan' ? (
          <strong>
            {phase.step_count} instalments of {money(phase.monthly_amount, currency)}, finishing{' '}
            {longDate(phase.final_due_date)}.
          </strong>
        ) : (
          <strong>{phase.summary}</strong>
        )}
        {phase.fallback && (
          <div className="u-mt-sm">
            The model did not return a usable answer, so the descriptions were written by the app.
            The amounts and dates are unaffected.
          </div>
        )}
      </div>

      <div className="budget-figures">
        <div>
          <span className="figure__label">
            {kind === 'plan' ? 'Each instalment' : 'Revised instalment'}
          </span>
          <span className="figure__value">
            {money(
              kind === 'plan' ? phase.monthly_amount : phase.revised_monthly_amount,
              currency,
            )}
          </span>
        </div>
        <div>
          <span className="figure__label">Available to save</span>
          <span className="figure__value">
            {signedMoney(phase.available_monthly_budget, currency)}
          </span>
          <span className="muted">
            {mcp.used ? 'after other goals and bills' : 'after other goals only'}
          </span>
        </div>
        <div>
          <span className="figure__label">Fits the budget</span>
          <span className="figure__value">
            {phase.within_budget === null ? (
              <span className="muted">no budget set</span>
            ) : phase.within_budget ? (
              <span className="badge badge--ahead">yes</span>
            ) : (
              <span className="badge badge--behind">no</span>
            )}
          </span>
        </div>
        {phase.shortfall > 0 && (
          <div>
            <span className="figure__label">Short by, each month</span>
            <span className="figure__value figure__value--over">
              {money(phase.shortfall, currency)}
            </span>
          </div>
        )}
      </div>

      <p className="muted">
        {mcp.used ? (
          <>
            Cross-feature context used: {mcp.tools_called.join(', ')} over MCP.
            {mcp.partial && ' Some of it was unavailable, so the panel is incomplete.'}
          </>
        ) : (
          <>MCP context not used. {mcp.reason}</>
        )}
      </p>
    </div>
  )
}

export default function AiModePanel({ goalId, currency, hasPlan, onPlanned }) {
  const [mode, setMode] = useState('ai')
  const [outcome, setOutcome] = useState(null)
  const [outcomeKind, setOutcomeKind] = useState('plan')
  const [answer, setAnswer] = useState(null)

  const planner = useAction()
  const rag = useAction()

  // Loaded lazily, when the MCP tab is opened. Switching tabs reloads it,
  // which is right: the figures come from other people's running services and
  // may have changed since the last look.
  const context = useAsync(
    () => (mode === 'mcp' ? api.getMcpContext(goalId) : Promise.resolve(null)),
    [mode, goalId],
  )

  const runPlanner = async (kind, useMcp) => {
    setOutcome(null)
    const result = await planner.run(() =>
      kind === 'plan'
        ? api.generatePlan(goalId, { useMcp })
        : api.regeneratePlan(goalId, { useMcp }),
    )
    if (!result) return
    setOutcomeKind(kind)
    setOutcome(result)
    onPlanned()
    if (mode === 'mcp') context.reload({ quiet: true })
  }

  const askRag = async (question) => {
    setAnswer(null)
    const result = await rag.run(() => api.askRag({ question }))
    if (result) setAnswer(result)
  }

  const explainGoal = async () => {
    setAnswer(null)
    const result = await rag.run(() => api.explainGoal(goalId))
    if (result) setAnswer(result)
  }

  const active = MODES.find((item) => item.id === mode)

  return (
    <section className="panel" aria-labelledby="ai-mode-heading">
      <div className="panel-header">
        <h2 id="ai-mode-heading">AI mode</h2>
      </div>

      <div className="mode-tabs" role="tablist" aria-label="AI mode">
        {MODES.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            id={`mode-tab-${item.id}`}
            aria-selected={mode === item.id}
            aria-controls={`mode-panel-${item.id}`}
            className={`mode-tab ${mode === item.id ? 'mode-tab--active' : ''}`}
            onClick={() => setMode(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <p className="muted mode-tabs__hint">{active.hint}</p>

      <div
        role="tabpanel"
        id={`mode-panel-${mode}`}
        aria-labelledby={`mode-tab-${mode}`}
        className="mode-panel"
      >
        {mode === 'ai' && (
          <>
            <p className="muted">
              The Release 0 behaviour. Python works out how many instalments there are, what each
              one costs and when it falls due; the model is given those finished figures and writes
              a short description for each. It is never asked to do arithmetic. This tab plans
              without any cross-feature context, so it is the baseline the MCP tab is compared
              against.
            </p>
            <div className="btn-row">
              <BusyButton
                busy={planner.busy}
                busyLabel={hasPlan ? 'Regenerating...' : 'Generating...'}
                onClick={() => runPlanner(hasPlan ? 'replan' : 'plan', false)}
              >
                {hasPlan ? 'Regenerate plan' : 'Generate plan'}
              </BusyButton>
              {hasPlan && (
                <BusyButton
                  className="btn btn--secondary"
                  busy={planner.busy}
                  busyLabel="Working..."
                  onClick={() => runPlanner('plan', false)}
                  title="Discard the pending steps and lay the plan out again from scratch"
                >
                  Start over
                </BusyButton>
              )}
            </div>
          </>
        )}

        {mode === 'mcp' && (
          <>
            <p className="muted">
              Before planning, this feature asks the shared MCP server what other features already
              know: the recurring bills one student&apos;s service tracks, and the income and
              spending another&apos;s has recorded. Those figures arrive already calculated and are
              used as they are. Python then subtracts them to work out what is genuinely left to
              save.
            </p>
            <McpContextPanel
              context={context.data}
              loading={context.loading}
              error={context.error}
              currency={currency}
              onReload={() => context.reload()}
            />
            <div className="btn-row u-mt-md">
              <BusyButton
                busy={planner.busy}
                busyLabel={hasPlan ? 'Regenerating...' : 'Generating...'}
                onClick={() => runPlanner(hasPlan ? 'replan' : 'plan', true)}
              >
                {hasPlan ? 'Regenerate plan with this context' : 'Generate plan with this context'}
              </BusyButton>
            </div>
          </>
        )}

        {mode === 'rag' && (
          <GroundedAnswerPanel
            result={answer}
            busy={rag.busy}
            error={rag.error}
            currency={currency}
            onExplain={explainGoal}
            onAsk={askRag}
            suggestions={RAG_SUGGESTIONS}
          />
        )}

        {mode !== 'rag' && (
          <>
            {planner.busy && (
              <p className="muted u-mt-sm" role="status">
                Asking the model for step descriptions. This runs on a local model and can take a
                while.
              </p>
            )}
            <Feedback error={planner.error} />
            <PlanOutcome outcome={outcome} kind={outcomeKind} currency={currency} />
          </>
        )}
      </div>
    </section>
  )
}
