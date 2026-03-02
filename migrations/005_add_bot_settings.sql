CREATE TABLE IF NOT EXISTS bot_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    auto_mode INTEGER DEFAULT 0
);

INSERT OR IGNORE INTO bot_settings (id, auto_mode)
VALUES (1, 0);