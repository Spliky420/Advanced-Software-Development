INSERT INTO transactions (
    transaction_date,
    merchant,
    description,
    amount,
    transaction_type,
    category,
    deduction_status,
    receipt_filename,
    notes
)
SELECT
    '2026-08-01',
    'Employer Payroll',
    'Monthly salary',
    3200.00,
    'income',
    'income',
    'not_reviewed',
    NULL,
    'Monthly salary payment'
WHERE NOT EXISTS (
    SELECT 1 FROM transactions
);

INSERT INTO transactions (
    transaction_date,
    merchant,
    description,
    amount,
    transaction_type,
    category,
    deduction_status,
    receipt_filename,
    notes
)
VALUES
(
    '2026-08-02',
    'Woolworths',
    'Weekly groceries',
    86.45,
    'expense',
    'groceries',
    'not_deductible',
    NULL,
    'Food and household items'
),
(
    '2026-08-03',
    'Shell',
    'Fuel',
    72.30,
    'expense',
    'transport',
    'needs_review',
    NULL,
    'Fuel purchase'
),
(
    '2026-08-04',
    'Officeworks',
    'Printer ink',
    89.95,
    'expense',
    'work',
    'potentially_deductible',
    NULL,
    'Printer ink for home office'
),
(
    '2026-08-05',
    'Netflix',
    'Monthly subscription',
    22.99,
    'expense',
    'entertainment',
    'not_deductible',
    NULL,
    'Streaming subscription'
),
(
    '2026-08-06',
    'Sydney Trains',
    'Opal travel',
    42.50,
    'expense',
    'transport',
    'not_deductible',
    NULL,
    'Public transport'
),
(
    '2026-08-07',
    'Chemist Warehouse',
    'Pharmacy purchase',
    38.75,
    'expense',
    'health',
    'not_deductible',
    NULL,
    'Personal health products'
),
(
    '2026-08-08',
    'University Bookshop',
    'Software engineering textbook',
    74.99,
    'expense',
    'education',
    'potentially_deductible',
    NULL,
    'Study-related textbook'
),
(
    '2026-08-09',
    'Origin Energy',
    'Electricity bill',
    145.60,
    'expense',
    'utilities',
    'needs_review',
    NULL,
    'Monthly electricity bill'
),
(
    '2026-08-10',
    'Freelance Client',
    'Website development payment',
    550.00,
    'income',
    'income',
    'not_reviewed',
    NULL,
    'Freelance income'
),
(
    '2026-08-11',
    'JB Hi-Fi',
    'USB-C hub',
    59.00,
    'expense',
    'work',
    'potentially_deductible',
    NULL,
    'Accessory used for work or study'
),
(
    '2026-08-12',
    'McDonalds',
    'Lunch',
    16.85,
    'expense',
    'other',
    'not_deductible',
    NULL,
    'Personal meal'
);