-- 005_create_signal_events.sql

CREATE TABLE IF NOT EXISTS signal_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER,
    direction TEXT, -- SELL / BUY
    signal REAL,
    threshold REAL,
    status TEXT, -- WAITING / TRIGGERED
    triggered_ts INTEGER
);