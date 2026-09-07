import { useState } from 'react'
import * as api from '../api/client'
import { useAction } from '../hooks'
import { Feedback } from './common'
import { money, todayIso } from '../format'

// Recording a contribution is the ACT phase of the agentic loop: the one
// place the user does something rather than plans something. No model is
// involved, which is why this form is instant where the plan buttons are not.
export default function ContributionForm({ goalId, currency, onRecorded }) {
  const [amount, setAmount] = useState('')
  const [date, setDate] = useState(todayIso())
  const [notes, setNotes] = useState('')
  const [fieldErrors, setFieldErrors] = useState({})
  const [success, setSuccess] = useState(null)
  const { busy, error, run } = useAction()

  const validate = () => {
    const found = {}
    const value = Number(amount)
    if (amount === '') found.amount = 'How much did you put in?'
    else if (!Number.isFinite(value)) found.amount = 'Enter a number.'
    else if (value <= 0) found.amount = 'The amount must be more than zero.'
    // Money that has not moved yet is a plan, not a contribution -- the same
    // rule the backend applies.
    if (date > todayIso()) found.contribution_date = 'You cannot record a contribution in the future.'
    return found
  }

  const submit = async (event) => {
    event.preventDefault()
    setSuccess(null)
    const found = validate()
    setFieldErrors(found)
    if (Object.keys(found).length > 0) return

    const result = await run(() =>
      api.createContribution(goalId, {
        amount: Number(amount),
        contribution_date: date,
        notes: notes.trim() || null,
      }),
    )
    if (result) {
      setAmount('')
      setNotes('')
      setDate(todayIso())
      setSuccess(
        result.goal.fully_funded
          ? `Recorded. That reaches the target of ${money(result.goal.target_amount, currency)} -- mark the goal achieved when you are ready.`
          : `Recorded. ${money(result.goal.saved_to_date, currency)} saved, ${money(result.goal.remaining_amount, currency)} to go.`,
      )
      onRecorded()
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <Feedback error={error} success={success} />

      <div className="field-row">
        <div className="field">
          <label htmlFor="contribution-amount">Amount ({currency})</label>
          <input
            id="contribution-amount"
            type="number"
            min="0.01"
            step="0.01"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            aria-invalid={Boolean(fieldErrors.amount)}
            placeholder="500"
          />
          {fieldErrors.amount && <span className="field__error">{fieldErrors.amount}</span>}
        </div>

        <div className="field">
          <label htmlFor="contribution-date">Date</label>
          <input
            id="contribution-date"
            type="date"
            max={todayIso()}
            value={date}
            onChange={(event) => setDate(event.target.value)}
            aria-invalid={Boolean(fieldErrors.contribution_date)}
          />
          {fieldErrors.contribution_date && (
            <span className="field__error">{fieldErrors.contribution_date}</span>
          )}
        </div>
      </div>

      <div className="field">
        <label htmlFor="contribution-notes">Notes (optional)</label>
        <input
          id="contribution-notes"
          value={notes}
          maxLength={500}
          onChange={(event) => setNotes(event.target.value)}
          placeholder="Payday transfer"
        />
      </div>

      <button type="submit" className="btn" disabled={busy}>
        {busy ? 'Recording...' : 'Log contribution'}
      </button>
    </form>
  )
}
