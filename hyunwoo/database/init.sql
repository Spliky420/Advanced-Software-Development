-- Stores bills and subscriptions.
CREATE TABLE IF NOT EXISTS bills (
    -- Unique record number.
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Main bill details.
    name TEXT NOT NULL,
    provider TEXT NOT NULL,
    category TEXT NOT NULL,

    -- The amount must be greater than zero.
    amount REAL NOT NULL CHECK (amount > 0),

    -- Allowed billing periods.
    billing_frequency TEXT NOT NULL CHECK (
        billing_frequency IN (
            'weekly',
            'fortnightly',
            'monthly',
            'quarterly',
            'yearly'
        )
    ),

    -- Dates use YYYY-MM-DD format.
    next_due_date TEXT NOT NULL,

    -- 0 means no and 1 means yes.
    auto_renew INTEGER NOT NULL DEFAULT 0 CHECK (auto_renew IN (0, 1)),

    -- Only used when there is a free trial.
    trial_end_date TEXT,

    -- Keeps track of active, paused and cancelled bills.
    status TEXT NOT NULL DEFAULT 'active' CHECK (
        status IN ('active', 'paused', 'cancelled')
    ),
    notes TEXT NOT NULL DEFAULT '',

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Prevent duplicate bills.
    UNIQUE (name, provider)
);
