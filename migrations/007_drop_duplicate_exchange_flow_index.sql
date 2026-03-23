-- 007_drop_duplicate_exchange_flow_index.sql

-- Удаляем дублирующий UNIQUE индекс,
-- который конфликтует с PRIMARY KEY (ts, cluster_id, flow_type)

DROP INDEX IF EXISTS ux_exchange_flow_ts_cluster_flow;