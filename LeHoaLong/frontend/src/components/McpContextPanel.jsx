// The MCP context panel: which tools were called, what each returned, and the
// available-to-save figure that came out of it.
//
// Everything rendered here was computed somewhere else and is displayed as
// received. The recurring-bills figure is HyunWoo's backend's; the budget and
// commitment figures are this backend's; the available-to-save figure is this
// backend's Python subtraction of the two. The `origin` on each term of the
// calculation comes from the API, so the provenance on screen is the API's
// claim rather than this component's guess.
//
// The unavailable state is a first-class rendering, not an error: a context
// that fell back to budget settings alone is still a context, and the panel
// says which happened and why.

import { useState } from 'react'
import { Feedback, Loading } from './common'
import { money, signedMoney } from '../format'

function ToolRow({ call }) {
  return (
    <tr>
      <td>
        <code>{call.tool}</code>
        <div className="muted mcp-tool__owner">{call.owner}</div>
      </td>
      <td>
        {call.is_error ? (
          <span className="badge badge--behind">failed</span>
        ) : (
          <span className="badge badge--ahead">ok</span>
        )}
      </td>
      <td className="numeric">{Math.round(call.duration_ms)} ms</td>
      <td>
        {call.is_error ? (
          <span className="mcp-tool__error">{call.error}</span>
        ) : (
          <span className="muted">returned figures</span>
        )}
      </td>
    </tr>
  )
}

function Calculation({ calculation, currency }) {
  return (
    <table className="table table--compact mcp-calculation">
      <caption className="muted">
        Computed in Python, never by the model. <code>{calculation.formula}</code>
      </caption>
      <tbody>
        {calculation.terms.map((term) => (
          <tr key={term.label}>
            <td className="mcp-calculation__operator">{term.operator}</td>
            <td>
              {term.label}
              <div className="muted mcp-calculation__origin">{term.origin}</div>
            </td>
            <td className="numeric">{money(term.amount, currency)}</td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr>
          <td className="mcp-calculation__operator">=</td>
          <th scope="row">Available to save each month</th>
          <td className="numeric">
            <strong>{signedMoney(calculation.result, currency)}</strong>
          </td>
        </tr>
      </tfoot>
    </table>
  )
}

export default function McpContextPanel({ context, loading, error, onReload, currency }) {
  const [showRaw, setShowRaw] = useState(false)

  if (loading) return <Loading what="context from the other features" />
  if (error) return <Feedback error={error} />
  if (!context) return null

  const { mcp, budget, committed_elsewhere: bills, observed } = context
  const used = mcp.used

  return (
    <div className="mcp-panel">
      {used ? (
        <div className={`callout ${mcp.partial ? 'callout--warning' : 'callout--success'}`}>
          <strong>
            {mcp.partial
              ? 'MCP partly available -- the bills figure was retrieved'
              : 'MCP context retrieved from two other features'}
          </strong>
          {mcp.reason && <div className="u-mt-sm">{mcp.reason}</div>}
        </div>
      ) : (
        <div className="callout callout--warning">
          <strong>MCP unavailable, using budget settings</strong>
          <div className="u-mt-sm">{mcp.reason}</div>
          <div className="u-mt-sm muted">
            Planning still works. The available figure below is this feature&apos;s own Release 0
            calculation, without any cross-feature context.
          </div>
        </div>
      )}

      <h3 className="mcp-panel__heading">Tools called</h3>
      {mcp.tools_called.length === 0 ? (
        <p className="empty-state">
          No tool was called{mcp.enabled ? '' : ' -- MCP is switched off by configuration'}.
        </p>
      ) : (
        <table className="table table--compact">
          <thead>
            <tr>
              <th scope="col">Tool and the feature that owns it</th>
              <th scope="col">Result</th>
              <th scope="col" className="numeric">
                Took
              </th>
              <th scope="col">Detail</th>
            </tr>
          </thead>
          <tbody>
            {mcp.tools_called.map((call) => (
              <ToolRow key={call.tool} call={call} />
            ))}
          </tbody>
        </table>
      )}
      {mcp.server_url && <p className="muted mcp-panel__url">over MCP at {mcp.server_url}</p>}

      <h3 className="mcp-panel__heading">What that leaves for saving</h3>
      <Calculation calculation={context.calculation} currency={currency} />

      {!budget.budget_is_set && (
        <div className="callout callout--info u-mt-sm">
          No monthly budget is set for this user, so there is no total to subtract from and no
          available-to-save figure. Set one in the budget panel on the dashboard.
        </div>
      )}

      <div className="mcp-figures">
        {bills?.monthly_bills != null && (
          <div>
            <span className="figure__label">Recurring bills each month</span>
            <span className="figure__value">{money(bills.monthly_bills, currency)}</span>
            <span className="muted">
              {bills.active_bill_count} active bills &middot; {bills.owner}
            </span>
          </div>
        )}
        {observed?.total_income != null && (
          <div>
            <span className="figure__label">Observed income</span>
            <span className="figure__value">{money(observed.total_income, currency)}</span>
            {/* Labelled with its period because the owning backend reports no
                period at all, and a reader must not take it for monthly. */}
            <span className="muted">over the {observed.period} &middot; {observed.owner}</span>
          </div>
        )}
        {observed?.total_expenses != null && (
          <div>
            <span className="figure__label">Observed spending</span>
            <span className="figure__value">{money(observed.total_expenses, currency)}</span>
            <span className="muted">over the {observed.period}</span>
          </div>
        )}
      </div>

      <div className="btn-row u-mt-md">
        <button type="button" className="btn btn--small btn--secondary" onClick={onReload}>
          Refresh context
        </button>
        <button
          type="button"
          className="btn btn--small btn--secondary"
          onClick={() => setShowRaw((shown) => !shown)}
          aria-expanded={showRaw}
        >
          {showRaw ? 'Hide' : 'Show'} the raw MCP response
        </button>
      </div>

      {/* The report needs protocol evidence rather than a description of it,
          and this is the same JSON the audit row stores. */}
      {showRaw && <pre className="code-block">{JSON.stringify(context, null, 2)}</pre>}
    </div>
  )
}
