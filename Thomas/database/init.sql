
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    transaction_date TEXT NOT NULL,

    merchant TEXT NOT NULL,

    description TEXT NOT NULL,

    amount REAL NOT NULL CHECK (amount >= 0),

    transaction_type TEXT NOT NULL
        CHECK (
            transaction_type IN (
                'income',
                'expense'
            )
        ),

    category TEXT NOT NULL DEFAULT 'uncategorised',

    deduction_status TEXT NOT NULL DEFAULT 'not_reviewed'
        CHECK (
            deduction_status IN (
                'not_reviewed',
                'potentially_deductible',
                'not_deductible',
                'needs_review'
            )
        ),

    receipt_filename TEXT,

    notes TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_transactions_date
ON transactions(transaction_date);

CREATE INDEX IF NOT EXISTS idx_transactions_merchant
ON transactions(merchant);

CREATE INDEX IF NOT EXISTS idx_transactions_category
ON transactions(category);

CREATE INDEX IF NOT EXISTS idx_transactions_type
ON transactions(transaction_type);

CREATE INDEX IF NOT EXISTS idx_transactions_deduction
ON transactions(deduction_status);