-- Adds 10 sample records for the demonstration.
-- Duplicate records are ignored if this runs again.
INSERT OR IGNORE INTO bills
(name, provider, category, amount, billing_frequency, next_due_date, auto_renew, trial_end_date, status, notes)
VALUES
-- Household services
('Electricity', 'Energy Australia', 'Utilities', 180.40, 'monthly', '2026-09-03', 0, NULL, 'active', 'Estimated monthly electricity bill'),
('Home Internet', 'Aussie Broadband', 'Utilities', 89.00, 'monthly', '2026-09-05', 1, NULL, 'active', 'Unlimited home internet'),
('Mobile Plan', 'Telstra', 'Telecommunications', 59.00, 'monthly', '2026-09-07', 1, NULL, 'active', 'Personal mobile service'),

-- Entertainment and health
('Netflix', 'Netflix', 'Entertainment', 25.99, 'monthly', '2026-09-02', 1, NULL, 'active', 'Streaming subscription'),
('Spotify', 'Spotify', 'Entertainment', 13.99, 'monthly', '2026-09-12', 1, NULL, 'active', 'Music subscription'),
('Gym Membership', 'Fitness First', 'Health', 29.95, 'fortnightly', '2026-08-31', 1, NULL, 'active', 'Currently overdue'),

-- Insurance and technology
('Car Insurance', 'NRMA', 'Insurance', 128.50, 'monthly', '2026-09-15', 1, NULL, 'active', 'Comprehensive vehicle insurance'),
('Cloud Storage', 'Apple iCloud+', 'Technology', 4.49, 'monthly', '2026-09-04', 1, NULL, 'active', 'Personal cloud storage'),
('Creative Software', 'Adobe', 'Software', 35.99, 'monthly', '2026-09-09', 1, NULL, 'active', 'Creative Cloud subscription'),

-- Example of a trial ending soon
('Design Software', 'Canva', 'Software', 17.99, 'monthly', '2026-09-06', 1, '2026-09-03', 'active', 'Trial ending soon');
