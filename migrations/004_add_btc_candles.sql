-- 004_add_btc_candles.sql
CREATE TABLE IF NOT EXISTS btc_candles_1m (
    open_time INTEGER PRIMARY KEY,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_btc_candles_1m_time
ON btc_candles_1m(open_time);