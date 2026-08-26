// Mirrors ASSET_CLASSES in joshua/backend/validation.py. The backend rejects
// anything outside this list, so the forms only ever offer these.
export const ASSET_CLASSES = [
  'Australian equities',
  'International equities',
  'ETFs',
  'REITs',
  'Government bonds',
  'Corporate bonds',
  'Cash',
  'Term deposits',
  'Commodities',
  'Crypto',
]

export const TARGET_SUM_TOLERANCE = 0.01
