-- 002_add_position_size.sql
ALTER TABLE trade_signals ADD COLUMN position_size REAL DEFAULT 0;