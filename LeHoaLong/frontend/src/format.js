// Display formatting. Nothing here calculates anything -- every figure shown
// was computed by the backend in Python; this only decides how it looks.

export function money(value, currency = 'AUD') {
  if (value === null || value === undefined) return '--'
  try {
    return new Intl.NumberFormat('en-AU', {
      style: 'currency',
      currency,
      maximumFractionDigits: 2,
    }).format(value)
  } catch {
    // An unrecognised currency code should not blank the page.
    return `${currency} ${Number(value).toFixed(2)}`
  }
}

// Signed, for the budget difference and the progress variance, where the sign
// carries the meaning.
export function signedMoney(value, currency = 'AUD') {
  if (value === null || value === undefined) return '--'
  const formatted = money(Math.abs(value), currency)
  return value < 0 ? `-${formatted}` : `+${formatted}`
}

export function percent(value) {
  if (value === null || value === undefined) return '--'
  return `${value.toFixed(1)}%`
}

export function longDate(iso) {
  if (!iso) return '--'
  const date = new Date(`${iso.slice(0, 10)}T00:00:00`)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function shortDate(iso) {
  if (!iso) return '--'
  const date = new Date(`${iso.slice(0, 10)}T00:00:00`)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: '2-digit' })
}

export const todayIso = () => new Date().toISOString().slice(0, 10)

const STATUS_LABELS = {
  on_track: 'On track',
  behind: 'Behind',
  ahead: 'Ahead',
  achieved: 'Achieved',
  active: 'Active',
  paused: 'Paused',
  abandoned: 'Abandoned',
  pending: 'Pending',
  complete: 'Complete',
  skipped: 'Skipped',
}

export const label = (value) => STATUS_LABELS[value] || value
