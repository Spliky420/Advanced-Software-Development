import { useState } from 'react'
import { Feedback } from './common'
import { todayIso } from '../format'

const PRIORITIES = ['high', 'medium', 'low']
const STATUSES = ['active', 'paused', 'achieved', 'abandoned']

const EMPTY = {
  name: '',
  target_amount: '',
  target_date: '',
  priority: 'medium',
  status: 'active',
}

// Client-side validation, mirroring the server's rules so the common mistakes
// are caught without a round trip. It is a convenience, never the authority:
// the same rules are enforced again in the backend, and a 400 from there is
// rendered alongside these (see the Feedback banner in the pages).
export function validate(values) {
  const errors = {}

  const name = values.name.trim()
  if (!name) errors.name = 'Give the goal a name.'
  else if (name.length > 120) errors.name = 'Keep the name to 120 characters or fewer.'

  const amount = Number(values.target_amount)
  if (values.target_amount === '') errors.target_amount = 'How much do you need to save?'
  else if (!Number.isFinite(amount)) errors.target_amount = 'Enter a number.'
  else if (amount <= 0) errors.target_amount = 'The target must be more than zero.'

  if (!values.target_date) {
    errors.target_date = 'Choose a target date.'
  } else if (values.status === 'active' && values.target_date < todayIso()) {
    // The same rule the backend applies, and for the same reason: the planner
    // divides what is left across the months remaining, so an active goal
    // with none left cannot be planned at all.
    errors.target_date = 'An active goal needs a target date in the future.'
  }

  return errors
}

export default function GoalForm({ initial, submitLabel, busy, serverError, onSubmit, onCancel }) {
  const [values, setValues] = useState(() => ({ ...EMPTY, ...initial }))
  const [errors, setErrors] = useState({})
  const [touched, setTouched] = useState(false)

  const change = (field) => (event) => {
    const next = { ...values, [field]: event.target.value }
    setValues(next)
    if (touched) setErrors(validate(next))
  }

  const submit = (event) => {
    event.preventDefault()
    setTouched(true)
    const found = validate(values)
    setErrors(found)
    if (Object.keys(found).length > 0) return
    onSubmit({
      name: values.name.trim(),
      target_amount: Number(values.target_amount),
      target_date: values.target_date,
      priority: values.priority,
      status: values.status,
    })
  }

  const errorFor = (field) =>
    errors[field] ? (
      <span className="field__error" id={`${field}-error`}>
        {errors[field]}
      </span>
    ) : null

  return (
    <form onSubmit={submit} noValidate>
      <Feedback error={serverError} />

      <div className="field">
        <label htmlFor="name">Goal name</label>
        <input
          id="name"
          value={values.name}
          onChange={change('name')}
          maxLength={120}
          aria-invalid={Boolean(errors.name)}
          aria-describedby={errors.name ? 'name-error' : undefined}
          placeholder="Emergency fund"
        />
        {errorFor('name')}
      </div>

      <div className="field-row">
        <div className="field">
          <label htmlFor="target_amount">Target amount</label>
          <input
            id="target_amount"
            type="number"
            min="0.01"
            step="0.01"
            value={values.target_amount}
            onChange={change('target_amount')}
            aria-invalid={Boolean(errors.target_amount)}
            aria-describedby={errors.target_amount ? 'target_amount-error' : undefined}
            placeholder="10000"
          />
          {errorFor('target_amount')}
        </div>

        <div className="field">
          <label htmlFor="target_date">Target date</label>
          <input
            id="target_date"
            type="date"
            value={values.target_date}
            onChange={change('target_date')}
            aria-invalid={Boolean(errors.target_date)}
            aria-describedby={errors.target_date ? 'target_date-error' : undefined}
          />
          {errorFor('target_date')}
        </div>
      </div>

      <div className="field-row">
        <div className="field">
          <label htmlFor="priority">Priority</label>
          <select id="priority" value={values.priority} onChange={change('priority')}>
            {PRIORITIES.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="status">Status</label>
          <select id="status" value={values.status} onChange={change('status')}>
            {STATUSES.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
          <span className="field__hint">Only active goals count toward your monthly budget.</span>
        </div>
      </div>

      <div className="btn-row">
        <button type="submit" className="btn" disabled={busy}>
          {busy ? 'Saving...' : submitLabel}
        </button>
        <button type="button" className="btn btn--secondary" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  )
}
