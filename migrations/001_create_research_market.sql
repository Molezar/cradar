-- 001_create_research_market.sql

CREATE TABLE IF NOT EXISTS research_market (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,

    whale_net REAL,
    exchange_net REAL,

    price REAL NOT NULL,

    price_15m REAL,
    price_1h REAL
);

-- индекс чтобы быстро искать старые записи
CREATE INDEX IF NOT EXISTS idx_research_market_ts
ON research_market(ts);