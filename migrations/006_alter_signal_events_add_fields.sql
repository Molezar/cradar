-- 006_alter_signal_events_add_fields.sql
ALTER TABLE signal_events ADD COLUMN exchange_ratio REAL;
ALTER TABLE signal_events ADD COLUMN volatility REAL;
ALTER TABLE signal_events ADD COLUMN delta_note TEXT;
ALTER TABLE signal_events ADD COLUMN cluster_concentration REAL;
ALTER TABLE signal_events ADD COLUMN price_change REAL;
ALTER TABLE signal_events ADD COLUMN p_up REAL;
ALTER TABLE signal_events ADD COLUMN p_down REAL;
ALTER TABLE signal_events ADD COLUMN triggered_ts INTEGER;