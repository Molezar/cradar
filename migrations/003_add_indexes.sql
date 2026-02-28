-- 003_add_indexes.sql
-- BTC price timestamp index
CREATE INDEX IF NOT EXISTS idx_price_ts ON btc_price(ts);

-- Exchange flow timestamp index
CREATE INDEX IF NOT EXISTS idx_flow_ts ON exchange_flow(ts);

-- Whale classification covering index
CREATE INDEX IF NOT EXISTS idx_whale_cover
ON whale_classification(btc, time DESC, txid, flow_type, from_cluster, to_cluster);

-- Exchange flow UNIQUE constraint replacement (SQLite-compatible)
CREATE UNIQUE INDEX IF NOT EXISTS ux_exchange_flow_ts_cluster_flow
ON exchange_flow(ts, cluster_id, flow_type);