import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { getTargets, putTargets } from '../api'
import { ASSET_CLASSES, TARGET_SUM_TOLERANCE } from '../constants'
import { useLoader } from '../hooks'
import { ErrorBanner, Loading, WarningBanner } from '../components/Feedback'
import { formatPercent } from '../format'

function toFormState(targets) {
  const byClass = new Map(targets.map((item) => [item.asset_class, item.target_percent]))
  const state = {}
  for (const assetClass of ASSET_CLASSES) {
    const value = byClass.get(assetClass)
    state[assetClass] = value == null ? '0' : String(value)
  }
  return state
}

function toNumber(value) {
  const parsed = Number(value)
  return Number.isNaN(parsed) ? 0 : parsed
}

export default function TargetsPage() {
  const { status, data, error, reload } = useLoader(getTargets, [])

  const [values, setValues] = useState(null)
  const [saveError, setSaveError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (data) setValues(toFormState(data))
  }, [data])

  const total = useMemo(
    () =>
      values
        ? ASSET_CLASSES.reduce((sum, assetClass) => sum + toNumber(values[assetClass]), 0)
        : 0,
    [values],
  )

  // The backend rejects a set that does not sum to 100, so the warning is live
  // rather than something the user only discovers on save.
  const sumsTo100 = Math.abs(total - 100) <= TARGET_SUM_TOLERANCE
  const difference = total - 100

  function setValue(assetClass, value) {
    setSaved(false)
    setValues((current) => ({ ...current, [assetClass]: value }))
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setSaving(true)
    setSaveError(null)
    setSaved(false)
    try {
      const payload = ASSET_CLASSES.map((assetClass) => ({
        asset_class: assetClass,
        target_percent: toNumber(values[assetClass]),
      }))
      const updated = await putTargets(payload)
      setValues(toFormState(updated))
      setSaved(true)
    } catch (failure) {
      setSaveError(failure)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="page">
      <header className="page-header">
        <h2>Target allocations</h2>
        <Link to="/allocation" className="button button-secondary">
          Back to allocation
        </Link>
      </header>

      {status === 'loading' && <Loading label="Loading targets..." />}
      <ErrorBanner error={error} onRetry={reload} title="Could not load the targets" />

      {status === 'ready' && values && (
        <form className="form" onSubmit={handleSubmit} noValidate>
          <p className="form-intro">
            Set the percentage of the portfolio each asset class should represent. The values must
            sum to 100 before they can be saved.
          </p>

          <ErrorBanner error={saveError} title="The targets could not be saved" />

          {saved && !saveError && (
            <div className="banner banner-success" role="status">
              Target allocations saved.
            </div>
          )}

          {!sumsTo100 && (
            <WarningBanner>
              <strong>Targets do not sum to 100.</strong> They currently sum to{' '}
              {formatPercent(total)} -- {formatPercent(Math.abs(difference))}{' '}
              {difference > 0 ? 'over' : 'under'}. Adjust them before saving.
            </WarningBanner>
          )}

          <div className="table-scroll">
            <table className="data-table targets-table">
              <thead>
                <tr>
                  <th scope="col">Asset class</th>
                  <th scope="col" className="numeric">Target %</th>
                </tr>
              </thead>
              <tbody>
                {ASSET_CLASSES.map((assetClass) => (
                  <tr key={assetClass}>
                    <th scope="row">
                      <label htmlFor={`target-${assetClass}`}>{assetClass}</label>
                    </th>
                    <td className="numeric">
                      <input
                        id={`target-${assetClass}`}
                        className="target-input"
                        type="number"
                        step="any"
                        min="0"
                        value={values[assetClass]}
                        onChange={(event) => setValue(assetClass, event.target.value)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className={sumsTo100 ? 'total-row' : 'total-row total-row-invalid'}>
                  <th scope="row">Total</th>
                  <td className="numeric">{formatPercent(total)}</td>
                </tr>
              </tfoot>
            </table>
          </div>

          <div className="form-actions">
            <button type="submit" className="button button-primary" disabled={saving}>
              {saving ? 'Saving...' : 'Save targets'}
            </button>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => {
                setValues(toFormState(data))
                setSaveError(null)
                setSaved(false)
              }}
              disabled={saving}
            >
              Reset
            </button>
          </div>
        </form>
      )}
    </section>
  )
}
