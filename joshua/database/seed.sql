-- seed.sql
-- Sample data for the portfolio/insight database (Joshua's microservice).
-- Assumes init.sql has already been run. All data is for demo user_id = 1.

-- ---------------------------------------------------------------------------
-- holdings: 16 positions across all 10 target asset classes, a mix of
-- gains (last_price > average_cost) and losses (last_price < average_cost).
-- ---------------------------------------------------------------------------
INSERT INTO holdings
    (user_id, ticker, asset_name, asset_class, units, average_cost, currency, last_price, price_as_at, purchase_date, notes)
VALUES
    -- Australian equities
    (1, 'CBA.AX', 'Commonwealth Bank of Australia', 'Australian equities', 50,    95.00,  'AUD', 162.50, '2026-08-22', '2021-03-15', 'Core bank holding, DRP enabled'),
    (1, 'BHP.AX', 'BHP Group Limited',               'Australian equities', 200,   45.00,  'AUD',  41.20, '2026-08-22', '2022-06-10', 'Bought during iron ore price dip'),
    (1, 'CSL.AX', 'CSL Limited',                      'Australian equities', 20,   310.00,  'AUD', 289.50, '2026-08-22', '2023-01-20', 'Healthcare exposure'),

    -- International equities
    (1, 'AAPL',   'Apple Inc.',                        'International equities', 30,   145.00,  'USD', 227.50, '2026-08-22', '2022-02-11', 'Long-term hold'),
    (1, 'MSFT',   'Microsoft Corporation',             'International equities', 15,   410.00,  'USD', 415.20, '2026-08-22', '2024-01-05', 'Added after cloud earnings beat'),

    -- ETFs
    (1, 'VAS.AX', 'Vanguard Australian Shares Index ETF',      'ETFs', 300,   85.00, 'AUD',  97.80, '2026-08-22', '2021-11-01', 'Core ASX 300 exposure'),
    (1, 'VGS.AX', 'Vanguard MSCI Index International Shares ETF', 'ETFs', 150, 98.00, 'AUD', 112.30, '2026-08-22', '2022-09-14', 'Unhedged global developed markets'),

    -- REITs
    (1, 'SCG.AX', 'Scentre Group',   'REITs', 500,   3.20, 'AUD',   3.45, '2026-08-22', '2020-07-22', 'Westfield shopping centres'),
    (1, 'GMG.AX', 'Goodman Group',   'REITs', 100,  22.50, 'AUD',  33.10, '2026-08-22', '2021-05-30', 'Industrial/logistics REIT'),

    -- Government bonds
    (1, 'VGB.AX', 'Vanguard Australian Government Bond Index ETF', 'Government bonds', 400, 51.00, 'AUD', 47.80, '2026-08-22', '2022-03-01', 'Defensive allocation, rate-sensitive'),

    -- Corporate bonds
    (1, 'VCF.AX', 'Vanguard Australian Corporate Fixed Interest Index ETF', 'Corporate bonds', 250, 49.50, 'AUD', 48.10, '2026-08-22', '2023-04-18', 'Investment-grade corporate debt'),

    -- Cash
    (1, 'CASH',   'AUD Cash (offset/settlement)', 'Cash', 15000, 1.00, 'AUD', 1.00, '2026-08-22', '2024-01-01', 'Sitting in brokerage settlement account'),

    -- Term deposits
    (1, 'TD-CBA-12M', 'CBA 12 Month Term Deposit @ 4.50% p.a.', 'Term deposits', 20000, 1.00, 'AUD', 1.00, '2026-08-22', '2024-02-15', 'Matures 2027-02-15'),

    -- Commodities
    (1, 'GOLD.AX', 'Global X Physical Gold', 'Commodities', 80, 24.00, 'AUD', 34.50, '2026-08-22', '2020-08-10', 'Inflation hedge'),

    -- Crypto
    (1, 'BTC', 'Bitcoin', 'Crypto', 0.25, 45000.00, 'AUD', 98000.00, '2026-08-22', '2023-11-20', 'Cold storage'),
    (1, 'ETH', 'Ethereum', 'Crypto', 3,   2800.00,  'AUD',  3400.00, '2026-08-22', '2024-03-05', 'Staked via exchange');

-- ---------------------------------------------------------------------------
-- allocation_targets: 10 rows for user_id = 1, one per asset class above,
-- target_percent values sum to exactly 100.
-- ---------------------------------------------------------------------------
INSERT INTO allocation_targets (user_id, asset_class, target_percent) VALUES
    (1, 'Australian equities',    20),
    (1, 'International equities', 15),
    (1, 'ETFs',                   15),
    (1, 'REITs',                  10),
    (1, 'Government bonds',       10),
    (1, 'Corporate bonds',         5),
    (1, 'Cash',                    5),
    (1, 'Term deposits',           5),
    (1, 'Commodities',             5),
    (1, 'Crypto',                 10);

-- ---------------------------------------------------------------------------
-- insight_log: 10 rows of past LLM interactions for user_id = 1.
-- prompt_sent contains figures already computed in Python; the model only
-- ever narrates/explains them, never calculates.
-- ---------------------------------------------------------------------------
INSERT INTO insight_log (user_id, created_at, request_type, prompt_sent, model_name, response_text) VALUES
    (1, '2026-01-12 09:14:00', 'portfolio_summary',
     'Portfolio total value: $118,432.50 AUD. Allocation: Australian equities 24.1%, International equities 13.8%, ETFs 18.2%, REITs 6.5%, Government bonds 9.9%, Corporate bonds 5.1%, Cash 6.3%, Term deposits 8.4%, Commodities 2.3%, Crypto 5.4%. Summarise this in plain English for the user.',
     'llama3.1:8b',
     'Your portfolio is worth just over $118k and is fairly well diversified. Australian shares are your biggest slice at roughly a quarter of the book, with a solid ETF base underneath. Defensive assets (bonds, cash and term deposits) make up about a quarter of the total, which gives you a reasonable buffer if equity markets pull back.'),

    (1, '2026-02-03 08:41:00', 'rebalance_suggestion',
     'Current vs target allocation deltas: Australian equities +4.1pp, International equities -1.2pp, ETFs +3.2pp, REITs -3.5pp, Government bonds -0.1pp, Corporate bonds +0.1pp, Cash +1.3pp, Term deposits +3.4pp, Commodities -2.7pp, Crypto -4.6pp. Suggest rebalancing actions based only on these figures.',
     'llama3.1:8b',
     'You are overweight Australian equities and ETFs relative to target, and underweight crypto and REITs. Consider trimming a small amount from your ASX and ETF positions and redirecting new contributions toward REITs and your crypto allocation to bring things back in line over the next quarter, rather than selling into a single lump.'),

    (1, '2026-02-28 17:02:00', 'performance_review',
     'Unrealised gains by holding: CBA.AX +$3,375.00, BHP.AX -$760.00, CSL.AX -$410.00, AAPL +$2,475.00 USD, MSFT +$78.00 USD, VAS.AX +$3,840.00, VGS.AX +$2,145.00, SCG.AX +$125.00, GMG.AX +$1,060.00, VGB.AX -$1,280.00, VCF.AX -$350.00, GOLD.AX +$840.00, BTC +$13,250.00, ETH +$1,800.00. Write a short performance summary.',
     'qwen2.5:0.5b',
     'Most of your holdings are sitting on gains, led by Bitcoin and your Vanguard Australian Shares ETF. The main laggards are BHP, CSL and your government bond ETF, all showing modest paper losses, which is typical given recent rate moves and commodity price softness.'),

    (1, '2026-03-15 12:20:00', 'diversification_review',
     'Number of distinct asset classes held: 10. Largest single holding as % of portfolio: BTC at 20.7%. Herfindahl-style concentration score: 0.148. Comment on diversification.',
     'llama3.1:8b',
     'You are spread across all ten major asset classes, which is a strong base for diversification. That said, Bitcoin alone makes up around a fifth of your total portfolio value, so a large crypto drawdown would have an outsized effect. Worth keeping an eye on whether that position keeps growing relative to the rest of the book.'),

    (1, '2026-04-09 07:55:00', 'goal_progress',
     'Goal: $150,000 portfolio value by 2028-01-01. Current value: $121,900.00. Required average annual growth to reach goal: 8.4%. Portfolio 3-year historical average annual growth: 9.7%. Comment on progress.',
     'llama3.1:8b',
     'Based on your recent growth trend, you are tracking ahead of what is needed to reach your $150,000 goal by 2028. If markets continue anywhere near your historical average, you could reach the target a little earlier than planned, though it is worth remembering past growth is no guarantee of future returns.'),

    (1, '2026-05-02 19:33:00', 'risk_check',
     'Defensive assets (cash, term deposits, government bonds) as % of portfolio: 23.6%. Growth assets (equities, ETFs, REITs, commodities, crypto) as % of portfolio: 71.3%. Corporate bonds: 5.1%. User stated risk tolerance: moderate-high. Comment on alignment.',
     'llama3.1:8b',
     'With roughly three quarters of your portfolio in growth assets and under a quarter in cash-like or government-bond defensives, your current mix looks broadly consistent with a moderate-high risk tolerance. Just be aware this weighting will amplify losses in a sharp downturn as much as it boosts gains in a rally.'),

    (1, '2026-05-27 10:11:00', 'tax_note',
     'Holdings eligible for CGT discount (held > 12 months) as of 2026-05-27: CBA.AX, BHP.AX, VAS.AX, VGS.AX, SCG.AX, GMG.AX, VGB.AX, GOLD.AX, BTC, ETH. Not yet eligible: CSL.AX, MSFT, VCF.AX. Summarise for the user, no tax advice.',
     'qwen2.5:0.5b',
     'Ten of your thirteen distinct positions have now been held for more than 12 months, which may make them eligible for the CGT discount if you were to sell. CSL, Microsoft and your corporate bond ETF are not yet past that mark. This is general information only, not tax advice -- check with an accountant before acting.'),

    (1, '2026-06-18 14:47:00', 'crypto_exposure_check',
     'Crypto allocation: 22.1% of portfolio (target 10%). BTC 15.9%, ETH 6.2%. Deviation from target: +12.1pp. Comment on this specific deviation.',
     'llama3.1:8b',
     'Crypto has run up to more than double your 10% target, driven mainly by Bitcoin. This is the largest single deviation in your portfolio right now. You might consider taking some profit here to bring the allocation back toward target and reduce concentration risk.'),

    (1, '2026-07-21 09:05:00', 'market_commentary',
     'User portfolio REIT exposure: 8.9% (target 10%). Recent context figures supplied by user: ASX 200 REIT sector total return last quarter +6.2%. No external market data was fetched by the model.',
     'llama3.1:8b',
     'Your REIT allocation is sitting close to target and the sector has had a reasonably strong quarter based on the figures you have supplied. No action seems necessary here for now -- just keep monitoring as part of your regular review.'),

    (1, '2026-08-10 16:29:00', 'quarterly_review',
     'Q3 snapshot: portfolio value $126,780.00 (+$8,348.00 vs last quarter, +7.0%). Best performer: BTC +18.4%. Worst performer: VGB.AX -3.1%. Cash buffer: 6.1% of portfolio, target 5%. Produce a quarterly summary.',
     'llama3.1:8b',
     'A solid quarter overall, up 7% to just under $127,000. Bitcoin was the standout contributor while your government bond ETF was the main drag, consistent with the broader rates environment. Your cash buffer is a touch above target, which is not a concern and gives you flexibility for the next rebalance.');
