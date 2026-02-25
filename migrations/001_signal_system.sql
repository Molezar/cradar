-- ============================================
-- DEMO ACCOUNT
-- ============================================

CREATE TABLE IF NOT EXISTS demo_account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    balance REAL NOT NULL,
    updated_at INTEGER
);

INSERT OR IGNORE INTO demo_account (id, balance, updated_at)
VALUES (1, 1000, strftime('%s','now'));

-- ============================================
-- TRADE SIGNALS
-- ============================================

CREATE TABLE IF NOT EXISTS trade_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at INTEGER,
    direction TEXT,
    entry REAL,
    stop REAL,
    take REAL,
    leverage INTEGER DEFAULT 5,
    status TEXT DEFAULT 'OPEN',  -- OPEN / TP / SL
    result REAL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_trade_status ON trade_signals(status);