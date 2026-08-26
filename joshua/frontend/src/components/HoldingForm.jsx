import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ASSET_CLASSES } from '../constants'
import { ErrorBanner } from './Feedback'

const FIELDS = [
  'ticker',
  'asset_name',
  'asset_class',
  'units',
  'average_cost',
  'currency',
  'last_price',
  'price_as_at',
  'purchase_date',
  'notes',
]

const EMPTY = {
  ticker: '',
  asset_name: '',
  asset_class: '',
  units: '',
  average_cost: '',
  currency: 'AUD',
  last_price: '',
  price_as_at: '',
  purchase_date: '',
  notes: '',
}

function toFormState(holding) {
  if (!holding) return EMPTY
  const state = { ...EMPTY }
  for (const field of FIELDS) {
    state[field] = holding[field] == null ? '' : String(holding[field])
  }
  return state
}

// Every backend validation message begins with the field it belongs to
// ("units must be a positive number"), so each one can be shown against its
// own input instead of only in the banner at the top.
function fieldErrorsFrom(error) {
  const mapped = {}
  if (!error || !error.errors) return mapped
  for (const message of error.errors) {
    const field = FIELDS.find((name) => message.startsWith(name))
    if (field && !mapped[field]) mapped[field] = message
  }
  return mapped
}

function numberOrNull(value) {
  if (value.trim() === '') return null
  const parsed = Number(value)
  return Number.isNaN(parsed) ? null : parsed
}

export default function HoldingForm({ holding, submitLabel, onSubmit, cancelTo }) {
  const [values, setValues] = useState(() => toFormState(holding))
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)

  const fieldErrors = fieldErrorsFrom(error)

  function setField(name, value) {
    setValues((current) => ({ ...current, [name]: value }))
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await onSubmit({
        ticker: values.ticker.trim(),
        asset_name: values.asset_name.trim(),
        asset_class: values.asset_class,
        units: numberOrNull(values.units),
        average_cost: numberOrNull(values.average_cost),
        currency: values.currency.trim(),
        last_price: numberOrNull(values.last_price),
        price_as_at: values.price_as_at || null,
        purchase_date: values.purchase_date,
        notes: values.notes.trim() === '' ? null : values.notes.trim(),
      })
    } catch (submitError) {
      setError(submitError)
      setSaving(false)
    }
  }

  function field(name, label, input, hint) {
    return (
      <div className={fieldErrors[name] ? 'form-field form-field-invalid' : 'form-field'}>
        <label htmlFor={name}>{label}</label>
        {input}
        {hint && !fieldErrors[name] && <p className="form-hint">{hint}</p>}
        {fieldErrors[name] && <p className="form-error">{fieldErrors[name]}</p>}
      </div>
    )
  }

  const textInput = (name, extra = {}) => (
    <input
      id={name}
      name={name}
      value={values[name]}
      onChange={(event) => setField(name, event.target.value)}
      aria-invalid={fieldErrors[name] ? 'true' : undefined}
      {...extra}
    />
  )

  return (
    <form className="form" onSubmit={handleSubmit} noValidate>
      <ErrorBanner error={error} title="The holding could not be saved" />

      <div className="form-grid">
        {field('ticker', 'Ticker', textInput('ticker', { placeholder: 'CBA.AX' }))}
        {field('asset_name', 'Asset name', textInput('asset_name', { placeholder: 'Commonwealth Bank of Australia' }))}

        {field(
          'asset_class',
          'Asset class',
          <select
            id="asset_class"
            name="asset_class"
            value={values.asset_class}
            onChange={(event) => setField('asset_class', event.target.value)}
            aria-invalid={fieldErrors.asset_class ? 'true' : undefined}
          >
            <option value="">Select an asset class...</option>
            {ASSET_CLASSES.map((assetClass) => (
              <option key={assetClass} value={assetClass}>
                {assetClass}
              </option>
            ))}
          </select>,
        )}

        {field('currency', 'Currency', textInput('currency', { placeholder: 'AUD' }))}
        {field('units', 'Units', textInput('units', { type: 'number', step: 'any', min: '0' }))}
        {field(
          'average_cost',
          'Average cost per unit',
          textInput('average_cost', { type: 'number', step: 'any', min: '0' }),
        )}
        {field(
          'last_price',
          'Last price per unit',
          textInput('last_price', { type: 'number', step: 'any', min: '0' }),
        )}
        {field('purchase_date', 'Purchase date', textInput('purchase_date', { type: 'date' }))}
        {field(
          'price_as_at',
          'Price as at',
          textInput('price_as_at', { type: 'date' }),
          'Optional -- the date the last price was observed.',
        )}
      </div>

      {field(
        'notes',
        'Notes',
        <textarea
          id="notes"
          name="notes"
          rows={3}
          value={values.notes}
          onChange={(event) => setField('notes', event.target.value)}
        />,
        'Optional.',
      )}

      <div className="form-actions">
        <button type="submit" className="button button-primary" disabled={saving}>
          {saving ? 'Saving...' : submitLabel}
        </button>
        <Link to={cancelTo} className="button button-secondary">
          Cancel
        </Link>
      </div>
    </form>
  )
}
