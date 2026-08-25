const money = new Intl.NumberFormat('en-AU', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const plain = new Intl.NumberFormat('en-AU', {
  minimumFractionDigits: 0,
  maximumFractionDigits: 8,
})

export function formatMoney(value) {
  if (value == null || Number.isNaN(value)) return '--'
  return `$${money.format(value)}`
}

// Explicit sign, so a gain and a loss are distinguishable without relying on
// colour alone.
export function formatSignedMoney(value) {
  if (value == null || Number.isNaN(value)) return '--'
  const sign = value > 0 ? '+' : value < 0 ? '-' : ''
  return `${sign}$${money.format(Math.abs(value))}`
}

export function formatUnits(value) {
  if (value == null || Number.isNaN(value)) return '--'
  return plain.format(value)
}

export function formatPercent(value, digits = 2) {
  if (value == null || Number.isNaN(value)) return '--'
  return `${value.toFixed(digits)}%`
}

// Drift is measured in percentage points, not percent -- the difference
// matters when reading it against a target percentage.
export function formatPercentagePoints(value, digits = 2) {
  if (value == null || Number.isNaN(value)) return '--'
  const sign = value > 0 ? '+' : value < 0 ? '-' : ''
  return `${sign}${Math.abs(value).toFixed(digits)} pp`
}

export function formatDate(value) {
  return value ? value : '--'
}

// One place decides what counts as a gain, a loss, or flat, so the table, the
// detail view and the totals never disagree.
export function changeClass(value, prefix = 'value') {
  if (value > 0) return `${prefix} ${prefix}-gain`
  if (value < 0) return `${prefix} ${prefix}-loss`
  return `${prefix} ${prefix}-flat`
}

// Drift gets its own vocabulary rather than reusing gain/loss: being above
// target is not a gain and being below it is not a loss, so the class names
// say overweight/underweight and can be themed independently.
export function driftClass(value) {
  if (value > 0) return 'drift drift-over'
  if (value < 0) return 'drift drift-under'
  return 'drift drift-on-target'
}

// The drift threshold is a number of percentage points, not a percentage of
// anything -- "5.00% points" would read as neither.
export function formatThresholdPoints(value, digits = 2) {
  if (value == null || Number.isNaN(value)) return '--'
  return `${value.toFixed(digits)} percentage points`
}
