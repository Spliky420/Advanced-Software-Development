-- seed.sql
-- Sample financial‑glossary terms for Maxwell's microservice.
-- Runs after init.sql to populate the table with demo data.

INSERT INTO terms (term, definition) VALUES
    ('Bear Market', 'A market condition where prices are falling or are expected to fall.'),
    ('Bull Market', 'A market condition where prices are rising or are expected to rise.'),
    ('Dividend', 'A distribution of a portion of a company''s earnings to its shareholders.'),
    ('ETF', 'Exchange-Traded Fund - a basket of securities that trades on an exchange.'),
    ('IPO', 'Initial Public Offering - the first sale of stock by a private company to the public.'),
    ('Liquidity', 'The ease with which an asset can be converted into cash without affecting its market price.'),
    ('Market Cap', 'Market Capitalization - the total market value of a company''s outstanding shares of stock.'),
    ('Volatility', 'A statistical measure of the dispersion of returns for a given security or market index.'),
    ('Arbitrage', 'The simultaneous purchase and sale of an asset to profit from a difference in the price.'),
    ('Broker', 'An individual or firm that executes buy and sell orders for securities on behalf of clients.'),
    ('Capital Gain', 'The profit from the sale of a capital asset such as stock, bond, or real estate.'),
    ('Commodity', 'A basic good used in commerce that is interchangeable with other goods of the same type.'),
    ('Derivative', 'A financial security with a value that is reliant upon or derived from an underlying asset or group of assets.'),
    ('Equity', 'Ownership interest in a corporation in the form of common stock or preferred stock.'),
    ('Futures', 'A standardized legal agreement to buy or sell something at a predetermined price at a specified time in the future.'),
    ('Hedge Fund', 'An investment fund that pools capital from accredited individuals or institutional investors and employs diverse strategies.'),
    ('Index Fund', 'A type of mutual fund with a portfolio constructed to match or track the components of a financial market index.'),
    ('Mutual Fund', 'An investment vehicle made up of a pool of money collected from many investors to invest in securities.'),
    ('Options', 'Financial derivatives that give buyers the right, but not the obligation, to buy or sell an underlying asset.'),
    ('Portfolio', 'A collection of financial investments like stocks, bonds, commodities, cash and cash equivalents.'),
    ('Recession', 'A significant decline in economic activity spread across the economy, lasting more than a few months.'),
    ('Share', 'A unit of ownership interest in a corporation or financial asset.'),
    ('Short Selling', 'The sale of a security that is not owned by the seller, or that the seller has borrowed.'),
    ('Spread', 'The difference between the bid price and the ask price of a security or asset.'),
    ('Yield', 'The income return on an investment, such as the interest or dividends received from holding a particular security.');
