import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { getAllocation } from '../api'
import { useLoader } from '../hooks'
import { EmptyState, ErrorBanner, Loading } from '../components/Feedback'
import {
  changeClass,
  formatMoney,
  formatPercent,
  formatSignedMoney,
  formatUnits,
} from '../format'

// /api/allocation returns every holding with its market value and gain/loss
// already computed by the backend. The frontend does no arithmetic of its own
// -- it only sorts and formats what Python worked out.
const COLUMNS = [
  { key: 'ticker', label: 'Ticker', numeric: false },
  { key: 'asset_name', label: 'Name', numeric: false },
  { key: 'asset_class', label: 'Asset class', numeric: false },
  { key: 'units', label: 'Units', numeric: true },
  { key: 'market_value', label: 'Market value', numeric: true },
  { key: 'gain_loss', label: 'Unrealised gain/loss', numeric: true },
]

function compare(a, b, key, numeric) {
  const left = a[key]
  const right = b[key]
  if (numeric) return (left ?? 0) - (right ?? 0)
  return String(left ?? '').localeCompare(String(right ?? ''))
}

export default function HoldingsPage() {
  const { status, data, error, reload } = useLoader(getAllocation, [])
  const [sort, setSort] = useState({ key: 'ticker', direction: 'asc' })

  const holdings = data ? data.holdings : []
  const portfolio = data ? data.portfolio : null

  const sorted = useMemo(() => {
    const column = COLUMNS.find((item) => item.key === sort.key)
    if (!column) return holdings
    const factor = sort.direction === 'asc' ? 1 : -1
    return [...holdings].sort((a, b) => compare(a, b, column.key, column.numeric) * factor)
  }, [holdings, sort])

  function toggleSort(key) {
    setSort((current) =>
      current.key === key
        ? { key, direction: current.direction === 'asc' ? 'desc' : 'asc' }
        : { key, direction: 'asc' },
    )
  }

  return (
    <section className="page">
      <header className="page-header">
        <h2>Holdings</h2>
        <Link to="/holdings/new" className="button button-primary">
          Add holding
        </Link>
      </header>

      {status === 'loading' && <Loading label="Loading holdings..." />}
      <ErrorBanner error={error} onRetry={reload} title="Could not load holdings" />

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
            <div className="summary-tile">
              <dt>Positions</dt>
              <dd>{holdings.length}</dd>
            </div>
          </dl>

          {holdings.length === 0 ? (
            <EmptyState>
              No holdings yet. <Link to="/holdings/new">Add the first one.</Link>
            </EmptyState>
          ) : (
            <div className="table-scroll">
              <table className="data-table holdings-table">
                <caption className="table-caption">
                  Select a column heading to sort. Currently sorted by{' '}
                  {COLUMNS.find((column) => column.key === sort.key)?.label} (
                  {sort.direction === 'asc' ? 'ascending' : 'descending'}).
                </caption>
                <thead>
                  <tr>
                    {COLUMNS.map((column) => {
                      const active = sort.key === column.key
                      return (
                        <th
                          key={column.key}
                          scope="col"
                          className={column.numeric ? 'numeric' : undefined}
                          aria-sort={
                            active
                              ? sort.direction === 'asc'
                                ? 'ascending'
                                : 'descending'
                              : 'none'
                          }
                        >
                          <button
                            type="button"
                            className={active ? 'sort-button sort-button-active' : 'sort-button'}
                            onClick={() => toggleSort(column.key)}
                          >
                            {column.label}
                            <span className="sort-indicator" aria-hidden="true">
                              {active ? (sort.direction === 'asc' ? '\u25b2' : '\u25bc') : '\u25c6'}
                            </span>
                          </button>
                        </th>
                      )
                    })}
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((holding) => (
                    <tr key={holding.id}>
                      <td>
                        <Link to={`/holdings/${holding.id}`} className="ticker-link">
                          {holding.ticker}
                        </Link>
                      </td>
                      <td>{holding.asset_name}</td>
                      <td>{holding.asset_class}</td>
                      <td className="numeric">{formatUnits(holding.units)}</td>
                      <td className="numeric">{formatMoney(holding.market_value)}</td>
                      <td className={`numeric ${changeClass(holding.gain_loss)}`}>
                        {formatSignedMoney(holding.gain_loss)}
                        <span className="value-secondary">
                          {formatPercent(holding.gain_loss_percent)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  )
}
