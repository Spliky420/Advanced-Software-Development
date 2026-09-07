-- seed.sql
-- Sample data for the Goals & Budgeting database (Le Hoa Long's microservice).
-- Assumes schema.sql has already been run.
--
-- Every table carries at least 10 rows (marking requirement). The data is
-- internally consistent and anchored to a "today" of 2026-09-03:
--
--   * contributions only ever reference goals that exist
--   * each goal's step amounts sum exactly to its target_amount
--   * step due dates run from just after the goal was created through to its
--     target_date, and contributions sit a day or two either side of the step
--     they pay off
--   * a goal's status matches its data -- 'achieved' goals are fully funded,
--     'abandoned' and 'paused' ones stall part-way through
--
-- Three user_ids (1, 2, 3) own goals, so ?user_id= filtering is demonstrable.
-- budget_settings covers ten users because the schema holds one current
-- budget per user (UNIQUE (user_id)) -- ten rows therefore means ten users.
-- Users 4-10 are budget-only: they have set a budget but not yet a goal.
--
-- Deliberate demo states, used by the demo script in docs/:
--   goal 1  Emergency Fund      slightly AHEAD of plan
--   goal 2  Japan Trip 2027     exactly ON TRACK
--   goal 3  New Laptop          BEHIND -- the replan/adapt demo
--   goal 7  Masters Tuition     no steps at all -- the "Generate plan" demo
--   goal 8  Road Bike           achieved, fully funded, all steps complete
--   goal 13 Holiday in Vietnam  no steps, no contributions -- zero-state case

-- ---------------------------------------------------------------------------
-- goals: 13 rows across 3 users, covering all four statuses and all three
-- priorities. goal_id is given explicitly so the child rows below can
-- reference it without relying on insertion order.
-- ---------------------------------------------------------------------------
INSERT INTO goals
    (goal_id, user_id, name, target_amount, target_date, priority, status, created_at, updated_at)
VALUES
    -- User 1 -- the primary demo user.
    (1,  1, 'Emergency Fund',              10000.00, '2027-03-31', 'high',   'active',    '2026-04-05T09:12:00', '2026-08-30T18:04:00'),
    (2,  1, 'Japan Trip 2027',              6000.00, '2027-06-30', 'medium', 'active',    '2026-07-10T20:41:00', '2026-08-28T19:55:00'),
    (3,  1, 'New Laptop',                   2800.00, '2026-12-15', 'high',   'active',    '2026-06-20T13:27:00', '2026-08-20T08:16:00'),
    (4,  1, 'Car Service and Rego',         1200.00, '2026-11-30', 'medium', 'active',    '2026-08-01T07:50:00', '2026-08-29T17:22:00'),
    (5,  1, 'Wedding Gift Fund',            1500.00, '2026-10-31', 'low',    'paused',    '2026-05-12T21:03:00', '2026-07-04T11:09:00'),
    (6,  1, 'Rental Bond and Moving Costs', 4200.00, '2027-01-31', 'high',   'active',    '2026-08-15T16:35:00', '2026-08-31T10:44:00'),
    (7,  1, 'Masters Tuition Deposit',      8000.00, '2027-08-31', 'medium', 'active',    '2026-09-01T12:00:00', '2026-09-01T12:00:00'),
    (8,  1, 'Road Bike',                    3500.00, '2026-06-30', 'low',    'achieved',  '2026-01-10T10:15:00', '2026-06-27T15:38:00'),

    -- User 2.
    (9,  2, 'Home Deposit',                60000.00, '2028-12-31', 'high',   'active',    '2026-02-01T08:00:00', '2026-08-30T09:12:00'),
    (10, 2, 'Festival Tickets',              900.00, '2026-10-15', 'low',    'active',    '2026-08-05T22:18:00', '2026-08-14T20:01:00'),
    (11, 2, 'Camera Upgrade',               2200.00, '2027-02-28', 'medium', 'abandoned', '2026-03-03T19:44:00', '2026-05-19T13:30:00'),

    -- User 3.
    (12, 3, 'Debt Payoff Buffer',           5000.00, '2027-05-31', 'high',   'active',    '2026-06-01T06:55:00', '2026-08-30T07:40:00'),
    (13, 3, 'Holiday in Vietnam',           3200.00, '2027-01-15', 'medium', 'active',    '2026-09-02T18:22:00', '2026-09-02T18:22:00');

-- ---------------------------------------------------------------------------
-- goal_steps: the savings plan for each goal. Amounts per goal sum exactly to
-- that goal's target_amount -- the last step absorbs the rounding remainder,
-- which is what the Python planner does too.
--
-- Steps due on or before 2026-09-03 are 'complete' where the matching
-- contribution exists, so the observe phase has something real to measure.
-- ---------------------------------------------------------------------------
INSERT INTO goal_steps
    (goal_id, step_order, description, step_amount, due_date, status, source, created_at)
VALUES
    -- Goal 1: Emergency Fund. 12 monthly steps of 834.00, last one 826.00
    -- (11 * 834 + 826 = 10000). Five months in and slightly ahead.
    (1,  1, 'Month 1 of 12 -- open the high-interest savings account and make the first deposit', 834.00, '2026-04-30', 'complete', 'ai', '2026-04-05T09:14:00'),
    (1,  2, 'Month 2 of 12 -- automatic transfer on payday',                                      834.00, '2026-05-31', 'complete', 'ai', '2026-04-05T09:14:00'),
    (1,  3, 'Month 3 of 12 -- automatic transfer on payday',                                      834.00, '2026-06-30', 'complete', 'ai', '2026-04-05T09:14:00'),
    (1,  4, 'Month 4 of 12 -- automatic transfer on payday',                                      834.00, '2026-07-31', 'complete', 'ai', '2026-04-05T09:14:00'),
    (1,  5, 'Month 5 of 12 -- automatic transfer on payday',                                      834.00, '2026-08-31', 'complete', 'ai', '2026-04-05T09:14:00'),
    (1,  6, 'Month 6 of 12 -- automatic transfer on payday',                                      834.00, '2026-09-30', 'pending',  'ai', '2026-04-05T09:14:00'),
    (1,  7, 'Month 7 of 12 -- automatic transfer on payday',                                      834.00, '2026-10-31', 'pending',  'ai', '2026-04-05T09:14:00'),
    (1,  8, 'Month 8 of 12 -- automatic transfer on payday',                                      834.00, '2026-11-30', 'pending',  'ai', '2026-04-05T09:14:00'),
    (1,  9, 'Month 9 of 12 -- automatic transfer on payday',                                      834.00, '2026-12-31', 'pending',  'ai', '2026-04-05T09:14:00'),
    (1, 10, 'Month 10 of 12 -- automatic transfer on payday',                                     834.00, '2027-01-31', 'pending',  'ai', '2026-04-05T09:14:00'),
    (1, 11, 'Month 11 of 12 -- automatic transfer on payday',                                     834.00, '2027-02-28', 'pending',  'ai', '2026-04-05T09:14:00'),
    (1, 12, 'Month 12 of 12 -- final top-up to reach the full three-month buffer',                826.00, '2027-03-31', 'pending',  'ai', '2026-04-05T09:14:00'),

    -- Goal 2: Japan Trip 2027. 12 monthly steps of 500.00 = 6000.00. On track.
    (2,  1, 'Month 1 of 12 -- book flights early and start the travel fund',      500.00, '2026-07-31', 'complete', 'ai', '2026-07-10T20:43:00'),
    (2,  2, 'Month 2 of 12 -- set aside the monthly travel amount',               500.00, '2026-08-31', 'complete', 'ai', '2026-07-10T20:43:00'),
    (2,  3, 'Month 3 of 12 -- set aside the monthly travel amount',               500.00, '2026-09-30', 'pending',  'ai', '2026-07-10T20:43:00'),
    (2,  4, 'Month 4 of 12 -- set aside the monthly travel amount',               500.00, '2026-10-31', 'pending',  'ai', '2026-07-10T20:43:00'),
    (2,  5, 'Month 5 of 12 -- set aside the monthly travel amount',               500.00, '2026-11-30', 'pending',  'ai', '2026-07-10T20:43:00'),
    (2,  6, 'Month 6 of 12 -- set aside the monthly travel amount',               500.00, '2026-12-31', 'pending',  'ai', '2026-07-10T20:43:00'),
    (2,  7, 'Month 7 of 12 -- pay the accommodation deposit from the fund',       500.00, '2027-01-31', 'pending',  'ai', '2026-07-10T20:43:00'),
    (2,  8, 'Month 8 of 12 -- set aside the monthly travel amount',               500.00, '2027-02-28', 'pending',  'ai', '2026-07-10T20:43:00'),
    (2,  9, 'Month 9 of 12 -- set aside the monthly travel amount',               500.00, '2027-03-31', 'pending',  'ai', '2026-07-10T20:43:00'),
    (2, 10, 'Month 10 of 12 -- set aside the monthly travel amount',              500.00, '2027-04-30', 'pending',  'ai', '2026-07-10T20:43:00'),
    (2, 11, 'Month 11 of 12 -- buy the rail pass and pocket money',               500.00, '2027-05-31', 'pending',  'ai', '2026-07-10T20:43:00'),
    (2, 12, 'Month 12 of 12 -- final top-up before departure',                    500.00, '2027-06-30', 'pending',  'ai', '2026-07-10T20:43:00'),

    -- Goal 3: New Laptop. 6 monthly steps, 5 * 467 + 465 = 2800. BEHIND: only
    -- the first step was ever completed, and step 2 is overdue.
    (3,  1, 'Month 1 of 6 -- put aside the first instalment',                     467.00, '2026-07-15', 'complete', 'ai', '2026-06-20T13:29:00'),
    (3,  2, 'Month 2 of 6 -- put aside the second instalment',                    467.00, '2026-08-15', 'pending',  'ai', '2026-06-20T13:29:00'),
    (3,  3, 'Month 3 of 6 -- put aside the third instalment',                     467.00, '2026-09-15', 'pending',  'ai', '2026-06-20T13:29:00'),
    (3,  4, 'Month 4 of 6 -- put aside the fourth instalment',                    467.00, '2026-10-15', 'pending',  'ai', '2026-06-20T13:29:00'),
    (3,  5, 'Month 5 of 6 -- compare prices and watch for a sale',                467.00, '2026-11-15', 'pending',  'ai', '2026-06-20T13:29:00'),
    (3,  6, 'Month 6 of 6 -- final instalment and purchase',                      465.00, '2026-12-15', 'pending',  'ai', '2026-06-20T13:29:00'),

    -- Goal 4: Car Service and Rego. 4 monthly steps of 300.00 = 1200.00.
    (4,  1, 'Month 1 of 4 -- start the vehicle sinking fund',                     300.00, '2026-08-31', 'complete', 'ai', '2026-08-01T07:52:00'),
    (4,  2, 'Month 2 of 4 -- monthly transfer to the vehicle fund',               300.00, '2026-09-30', 'pending',  'ai', '2026-08-01T07:52:00'),
    (4,  3, 'Month 3 of 4 -- book the service and confirm the quote',             300.00, '2026-10-31', 'pending',  'ai', '2026-08-01T07:52:00'),
    (4,  4, 'Month 4 of 4 -- pay registration and the service invoice',           300.00, '2026-11-30', 'pending',  'ai', '2026-08-01T07:52:00'),

    -- Goal 5: Wedding Gift Fund. Hand-written by the user, then paused.
    -- 750 + 750 = 1500. Step 2 skipped when the goal was paused.
    (5,  1, 'Put aside half the gift amount after the June pay run',              750.00, '2026-06-30', 'complete', 'user', '2026-05-12T21:05:00'),
    (5,  2, 'Put aside the remaining half before the RSVP deadline',              750.00, '2026-08-31', 'skipped',  'user', '2026-05-12T21:05:00'),

    -- Goal 6: Rental Bond and Moving Costs. 6 monthly steps of 700 = 4200.
    (6,  1, 'Month 1 of 6 -- start the bond fund and get quotes from movers',     700.00, '2026-08-31', 'complete', 'ai', '2026-08-15T16:37:00'),
    (6,  2, 'Month 2 of 6 -- monthly transfer to the bond fund',                  700.00, '2026-09-30', 'pending',  'ai', '2026-08-15T16:37:00'),
    (6,  3, 'Month 3 of 6 -- monthly transfer to the bond fund',                  700.00, '2026-10-31', 'pending',  'ai', '2026-08-15T16:37:00'),
    (6,  4, 'Month 4 of 6 -- book the removalist and pay the deposit',            700.00, '2026-11-30', 'pending',  'ai', '2026-08-15T16:37:00'),
    (6,  5, 'Month 5 of 6 -- monthly transfer to the bond fund',                  700.00, '2026-12-31', 'pending',  'ai', '2026-08-15T16:37:00'),
    (6,  6, 'Month 6 of 6 -- pay the bond and the first fortnight of rent',       700.00, '2027-01-31', 'pending',  'ai', '2026-08-15T16:37:00'),

    -- Goal 8: Road Bike. Achieved -- 5 * 583 + 585 = 3500, every step complete.
    (8,  1, 'Month 1 of 6 -- open the bike fund',                                 583.00, '2026-01-31', 'complete', 'ai', '2026-01-10T10:17:00'),
    (8,  2, 'Month 2 of 6 -- monthly transfer',                                   583.00, '2026-02-28', 'complete', 'ai', '2026-01-10T10:17:00'),
    (8,  3, 'Month 3 of 6 -- monthly transfer',                                   583.00, '2026-03-31', 'complete', 'ai', '2026-01-10T10:17:00'),
    (8,  4, 'Month 4 of 6 -- monthly transfer, test ride shortlisted frames',     583.00, '2026-04-30', 'complete', 'ai', '2026-01-10T10:17:00'),
    (8,  5, 'Month 5 of 6 -- monthly transfer',                                   583.00, '2026-05-31', 'complete', 'ai', '2026-01-10T10:17:00'),
    (8,  6, 'Month 6 of 6 -- final instalment and purchase',                      585.00, '2026-06-30', 'complete', 'ai', '2026-01-10T10:17:00'),

    -- Goal 9: Home Deposit. Long horizon, so quarterly rather than monthly:
    -- 12 quarters of 5000.00 = 60000.00. Ahead of plan.
    (9,  1, 'Quarter 1 of 12 -- open the first home saver account',              5000.00, '2026-03-31', 'complete', 'ai', '2026-02-01T08:03:00'),
    (9,  2, 'Quarter 2 of 12 -- quarterly transfer',                             5000.00, '2026-06-30', 'complete', 'ai', '2026-02-01T08:03:00'),
    (9,  3, 'Quarter 3 of 12 -- quarterly transfer',                             5000.00, '2026-09-30', 'pending',  'ai', '2026-02-01T08:03:00'),
    (9,  4, 'Quarter 4 of 12 -- quarterly transfer, review the interest rate',   5000.00, '2026-12-31', 'pending',  'ai', '2026-02-01T08:03:00'),
    (9,  5, 'Quarter 5 of 12 -- quarterly transfer',                             5000.00, '2027-03-31', 'pending',  'ai', '2026-02-01T08:03:00'),
    (9,  6, 'Quarter 6 of 12 -- quarterly transfer',                             5000.00, '2027-06-30', 'pending',  'ai', '2026-02-01T08:03:00'),
    (9,  7, 'Quarter 7 of 12 -- quarterly transfer',                             5000.00, '2027-09-30', 'pending',  'ai', '2026-02-01T08:03:00'),
    (9,  8, 'Quarter 8 of 12 -- quarterly transfer, check first home buyer schemes', 5000.00, '2027-12-31', 'pending', 'ai', '2026-02-01T08:03:00'),
    (9,  9, 'Quarter 9 of 12 -- quarterly transfer',                             5000.00, '2028-03-31', 'pending',  'ai', '2026-02-01T08:03:00'),
    (9, 10, 'Quarter 10 of 12 -- quarterly transfer',                            5000.00, '2028-06-30', 'pending',  'ai', '2026-02-01T08:03:00'),
    (9, 11, 'Quarter 11 of 12 -- quarterly transfer, obtain pre-approval',       5000.00, '2028-09-30', 'pending',  'ai', '2026-02-01T08:03:00'),
    (9, 12, 'Quarter 12 of 12 -- final transfer, deposit ready',                 5000.00, '2028-12-31', 'pending',  'ai', '2026-02-01T08:03:00'),

    -- Goal 10: Festival Tickets. 3 monthly steps of 300.00 = 900.00.
    (10, 1, 'Month 1 of 3 -- set aside the first third',                          300.00, '2026-08-15', 'complete', 'ai', '2026-08-05T22:20:00'),
    (10, 2, 'Month 2 of 3 -- set aside the second third',                         300.00, '2026-09-15', 'pending',  'ai', '2026-08-05T22:20:00'),
    (10, 3, 'Month 3 of 3 -- buy the tickets when the ballot opens',              300.00, '2026-10-15', 'pending',  'ai', '2026-08-05T22:20:00'),

    -- Goal 11: Camera Upgrade. Abandoned -- both steps skipped.
    -- 1100 + 1100 = 2200.
    (11, 1, 'Half 1 of 2 -- save toward the body',                               1100.00, '2026-08-31', 'skipped',  'ai', '2026-03-03T19:46:00'),
    (11, 2, 'Half 2 of 2 -- save toward the lens',                               1100.00, '2027-02-28', 'skipped',  'ai', '2026-03-03T19:46:00'),

    -- Goal 12: Debt Payoff Buffer. 12 monthly steps, 11 * 417 + 413 = 5000.
    (12,  1, 'Month 1 of 12 -- build the first month of buffer',                  417.00, '2026-06-30', 'complete', 'ai', '2026-06-01T06:57:00'),
    (12,  2, 'Month 2 of 12 -- monthly transfer to the buffer',                   417.00, '2026-07-31', 'complete', 'ai', '2026-06-01T06:57:00'),
    (12,  3, 'Month 3 of 12 -- monthly transfer to the buffer',                   417.00, '2026-08-31', 'complete', 'ai', '2026-06-01T06:57:00'),
    (12,  4, 'Month 4 of 12 -- monthly transfer to the buffer',                   417.00, '2026-09-30', 'pending',  'ai', '2026-06-01T06:57:00'),
    (12,  5, 'Month 5 of 12 -- monthly transfer to the buffer',                   417.00, '2026-10-31', 'pending',  'ai', '2026-06-01T06:57:00'),
    (12,  6, 'Month 6 of 12 -- monthly transfer to the buffer',                   417.00, '2026-11-30', 'pending',  'ai', '2026-06-01T06:57:00'),
    (12,  7, 'Month 7 of 12 -- monthly transfer, review the card interest rate',  417.00, '2026-12-31', 'pending',  'ai', '2026-06-01T06:57:00'),
    (12,  8, 'Month 8 of 12 -- monthly transfer to the buffer',                   417.00, '2027-01-31', 'pending',  'ai', '2026-06-01T06:57:00'),
    (12,  9, 'Month 9 of 12 -- monthly transfer to the buffer',                   417.00, '2027-02-28', 'pending',  'ai', '2026-06-01T06:57:00'),
    (12, 10, 'Month 10 of 12 -- monthly transfer to the buffer',                  417.00, '2027-03-31', 'pending',  'ai', '2026-06-01T06:57:00'),
    (12, 11, 'Month 11 of 12 -- monthly transfer to the buffer',                  417.00, '2027-04-30', 'pending',  'ai', '2026-06-01T06:57:00'),
    (12, 12, 'Month 12 of 12 -- final transfer, one month of expenses covered',   413.00, '2027-05-31', 'pending',  'ai', '2026-06-01T06:57:00');

-- ---------------------------------------------------------------------------
-- contributions: money actually paid in. 26 rows across 11 of the 13 goals.
-- Goals 7 and 13 deliberately have none -- they are the zero-contribution
-- edge case the progress tests and the demo both rely on.
-- ---------------------------------------------------------------------------
INSERT INTO contributions
    (goal_id, amount, contribution_date, notes)
VALUES
    -- Goal 1: 4202.00 paid against 4170.00 required to date -- slightly ahead.
    (1,  834.00, '2026-04-28', 'Opening deposit into the high-interest account'),
    (1,  834.00, '2026-05-30', 'Automatic payday transfer'),
    (1,  900.00, '2026-06-29', 'Payday transfer plus the tax refund rounding'),
    (1,  800.00, '2026-07-31', 'Short this month -- car tyres'),
    (1,  834.00, '2026-08-30', 'Automatic payday transfer'),

    -- Goal 2: 1000.00 paid against 1000.00 required -- exactly on track.
    (2,  500.00, '2026-07-30', 'First travel fund transfer'),
    (2,  500.00, '2026-08-28', 'Monthly travel fund transfer'),

    -- Goal 3: 450.00 paid against 934.00 required -- behind by 484.00.
    (3,  300.00, '2026-07-14', 'Partial -- less than the planned instalment'),
    (3,  150.00, '2026-08-20', 'Whatever was left after rent'),

    -- Goal 4: on plan.
    (4,  300.00, '2026-08-29', 'First transfer to the vehicle sinking fund'),

    -- Goal 5: paused after the first half.
    (5,  750.00, '2026-06-28', 'Half the gift amount, then the wedding was postponed'),

    -- Goal 6: on plan.
    (6,  700.00, '2026-08-31', 'First bond instalment'),

    -- Goal 8: achieved -- 3500.00 paid, exactly the target.
    (8,  583.00, '2026-01-30', 'Bike fund opened'),
    (8,  583.00, '2026-02-27', 'Monthly transfer'),
    (8,  583.00, '2026-03-31', 'Monthly transfer'),
    (8,  583.00, '2026-04-30', 'Monthly transfer'),
    (8,  583.00, '2026-05-29', 'Monthly transfer'),
    (8,  585.00, '2026-06-27', 'Final instalment -- bike collected'),

    -- Goal 9: 12000.00 paid against 10000.00 required -- ahead.
    (9, 5000.00, '2026-03-30', 'First quarterly deposit'),
    (9, 5000.00, '2026-06-28', 'Second quarterly deposit'),
    (9, 2000.00, '2026-08-30', 'Bonus paid in early, put straight into the deposit'),

    -- Goal 10: on plan.
    (10, 300.00, '2026-08-14', 'First third set aside'),

    -- Goal 11: abandoned after one small contribution.
    (11, 150.00, '2026-04-02', 'Small start, then decided to keep the current camera'),

    -- Goal 12: 1251.00 paid against 1251.00 required -- exactly on track.
    (12, 417.00, '2026-06-29', 'Buffer month 1'),
    (12, 417.00, '2026-07-30', 'Buffer month 2'),
    (12, 417.00, '2026-08-30', 'Buffer month 3');

-- ---------------------------------------------------------------------------
-- ai_plan_log: 12 rows of audit trail, one per agentic-loop phase actually
-- run against the seeded goals.
--
-- model_name is the literal 'python' where no model was involved: the observe
-- phase is pure arithmetic, and the two 'fallback' plan rows are the
-- deterministic even split standing in after the model returned unusable
-- JSON. That is exactly how those rows read in production.
--
-- Prompts are shortened for readability but keep the shape the real prompt
-- builder produces: finished figures in, no arithmetic asked of the model.
-- ---------------------------------------------------------------------------
INSERT INTO ai_plan_log
    (goal_id, phase, model_name, prompt, response, created_at)
VALUES
    (1, 'plan', 'qwen2.5:0.5b',
     'Goal: Emergency Fund. Target 10000.00 AUD by 2027-03-31. Months remaining: 12. Amount per month (already calculated): 834.00, final month 826.00. Available monthly budget: 2500.00. Return JSON {"steps":[{"step_order":int,"description":str,"step_amount":number,"due_date":"YYYY-MM-DD"}]} using exactly the amounts and dates supplied.',
     '{"steps": [{"step_order": 1, "description": "Month 1 of 12 -- open the high-interest savings account and make the first deposit", "step_amount": 834.00, "due_date": "2026-04-30"}, "... 11 further steps ..."]}',
     '2026-04-05T09:14:00'),

    (1, 'observe', 'python',
     'Observation for goal 1 (Emergency Fund) at 2026-08-30: saved to date 4202.00, required to date 4170.00, variance +32.00, status on_track.',
     '{"status": "on_track", "saved_to_date": 4202.00, "required_to_date": 4170.00, "variance": 32.00, "projected_completion_date": "2027-03-31"}',
     '2026-08-30T18:04:00'),

    (2, 'plan', 'qwen2.5:0.5b',
     'Goal: Japan Trip 2027. Target 6000.00 AUD by 2027-06-30. Months remaining: 12. Amount per month (already calculated): 500.00. Available monthly budget: 2500.00. Return JSON {"steps":[...]} using exactly the amounts and dates supplied.',
     '{"steps": [{"step_order": 1, "description": "Month 1 of 12 -- book flights early and start the travel fund", "step_amount": 500.00, "due_date": "2026-07-31"}, "... 11 further steps ..."]}',
     '2026-07-10T20:43:00'),

    (2, 'observe', 'python',
     'Observation for goal 2 (Japan Trip 2027) at 2026-08-28: saved to date 1000.00, required to date 1000.00, variance 0.00, status on_track.',
     '{"status": "on_track", "saved_to_date": 1000.00, "required_to_date": 1000.00, "variance": 0.00, "projected_completion_date": "2027-06-30"}',
     '2026-08-28T19:55:00'),

    (3, 'plan', 'qwen2.5:0.5b',
     'Goal: New Laptop. Target 2800.00 AUD by 2026-12-15. Months remaining: 6. Amount per month (already calculated): 467.00, final month 465.00. Available monthly budget: 2500.00. Return JSON {"steps":[...]} using exactly the amounts and dates supplied.',
     '{"steps": [{"step_order": 1, "description": "Month 1 of 6 -- put aside the first instalment", "step_amount": 467.00, "due_date": "2026-07-15"}, "... 5 further steps ..."]}',
     '2026-06-20T13:29:00'),

    (3, 'observe', 'python',
     'Observation for goal 3 (New Laptop) at 2026-08-20: saved to date 450.00, required to date 934.00, variance -484.00, status behind.',
     '{"status": "behind", "saved_to_date": 450.00, "required_to_date": 934.00, "variance": -484.00, "projected_completion_date": "2027-08-15"}',
     '2026-08-20T08:16:00'),

    (3, 'adapt', 'qwen2.5:0.5b',
     'Goal: New Laptop is behind by 484.00. Remaining amount 2350.00 across 4 remaining months. Revised amount per month (already calculated): 587.50. Completed steps must not change. Rewrite only step_order 3 to 6. Return JSON {"steps":[...],"summary":str}.',
     '{"steps": [{"step_order": 3, "description": "Catch-up month -- raise the transfer to cover the shortfall", "step_amount": 587.50, "due_date": "2026-09-15"}, "... 3 further steps ..."], "summary": "You are 484.00 behind on the laptop goal. Lifting the remaining four instalments to 587.50 brings it back on schedule by 2026-12-15."}',
     '2026-08-20T08:17:00'),

    (8, 'plan', 'python',
     'Goal: Road Bike. Target 3500.00 AUD by 2026-06-30. Months remaining: 6. Amount per month (already calculated): 583.00, final month 585.00. FALLBACK: the model returned unparseable JSON twice, so this even-split plan was generated deterministically in Python.',
     '{"steps": [{"step_order": 1, "description": "Month 1 of 6 -- open the bike fund", "step_amount": 583.00, "due_date": "2026-01-31"}, "... 5 further steps ..."], "note": "fallback"}',
     '2026-01-10T10:17:00'),

    (8, 'observe', 'python',
     'Observation for goal 8 (Road Bike) at 2026-06-27: saved to date 3500.00, required to date 3500.00, variance 0.00, status achieved.',
     '{"status": "achieved", "saved_to_date": 3500.00, "required_to_date": 3500.00, "variance": 0.00, "projected_completion_date": "2026-06-27"}',
     '2026-06-27T15:38:00'),

    (9, 'plan', 'llama3.1:8b',
     'Goal: Home Deposit. Target 60000.00 AUD by 2028-12-31. Quarters remaining: 12. Amount per quarter (already calculated): 5000.00. Available monthly budget: 6000.00. Return JSON {"steps":[...]} using exactly the amounts and dates supplied.',
     '{"steps": [{"step_order": 1, "description": "Quarter 1 of 12 -- open the first home saver account", "step_amount": 5000.00, "due_date": "2026-03-31"}, "... 11 further steps ..."]}',
     '2026-02-01T08:03:00'),

    (9, 'observe', 'python',
     'Observation for goal 9 (Home Deposit) at 2026-08-30: saved to date 12000.00, required to date 10000.00, variance +2000.00, status ahead.',
     '{"status": "ahead", "saved_to_date": 12000.00, "required_to_date": 10000.00, "variance": 2000.00, "projected_completion_date": "2028-10-31"}',
     '2026-08-30T09:12:00'),

    (12, 'plan', 'python',
     'Goal: Debt Payoff Buffer. Target 5000.00 AUD by 2027-05-31. Months remaining: 12. Amount per month (already calculated): 417.00, final month 413.00. FALLBACK: the model timed out, so this even-split plan was generated deterministically in Python.',
     '{"steps": [{"step_order": 1, "description": "Month 1 of 12 -- build the first month of buffer", "step_amount": 417.00, "due_date": "2026-06-30"}, "... 11 further steps ..."], "note": "fallback"}',
     '2026-06-01T06:57:00');

-- ---------------------------------------------------------------------------
-- budget_settings: one current monthly budget per user (UNIQUE (user_id)), so
-- ten rows means ten users. Users 1-3 own the goals above; users 4-10 have
-- set a budget but no goals yet, which is also the state a brand new user is
-- in and worth having seeded.
--
-- User 1 is deliberately OVER budget: their active goals commit roughly
-- 2801.00 per month against a 2500.00 budget, so the frontend's warning
-- state is visible the moment the stack comes up.
-- ---------------------------------------------------------------------------
INSERT INTO budget_settings
    (user_id, monthly_budget, currency, updated_at)
VALUES
    (1,  2500.00, 'AUD', '2026-08-01T08:00:00'),
    (2,  6000.00, 'AUD', '2026-07-15T10:30:00'),
    (3,  1400.00, 'AUD', '2026-06-01T06:50:00'),
    (4,  3200.00, 'AUD', '2026-05-20T14:05:00'),
    (5,   950.00, 'AUD', '2026-08-11T19:20:00'),
    (6,  4500.00, 'AUD', '2026-03-28T09:45:00'),
    (7,  1800.00, 'NZD', '2026-08-22T21:10:00'),
    (8,   700.00, 'AUD', '2026-02-14T12:00:00'),
    (9,  5200.00, 'USD', '2026-07-02T07:35:00'),
    (10, 2100.00, 'AUD', '2026-08-29T16:48:00');
