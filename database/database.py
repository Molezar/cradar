import sqlite3
from pathlib import Path
from config import Config

DB_PATH = Config.DB_PATH


def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    # =====================================================
    # 1. Whale transactions (raw large tx storage)
    # =====================================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS whale_tx (
        txid TEXT PRIMARY KEY,
        btc REAL,
        time INTEGER
    )
    """)

    # =====================================================
    # 2. Addresses (all seen addresses)
    # =====================================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS addresses (
        address TEXT PRIMARY KEY,
        first_seen INTEGER,
        last_seen INTEGER,
        total_in REAL DEFAULT 0,
        total_out REAL DEFAULT 0,
        tx_count INTEGER DEFAULT 0
    )
    """)

    # =====================================================
    # 3. Transaction IO mapping
    # =====================================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS tx_inputs (
        txid TEXT,
        address TEXT,
        btc REAL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS tx_outputs (
        txid TEXT,
        address TEXT,
        btc REAL
    )
    """)

    # =====================================================
    # 4. Unified Clusters (EXCHANGE + BEHAVIORAL)
    # =====================================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS clusters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cluster_type TEXT NOT NULL,        -- EXCHANGE / BEHAVIORAL
        name TEXT,                         -- Binance / Kraken / NULL
        subtype TEXT,                      -- HOT / COLD / OTC / HUB / NULL
        confidence REAL DEFAULT 0.0,
        size INTEGER DEFAULT 0,
        created_at INTEGER,
        last_updated INTEGER
    )
    """)

    # =====================================================
    # 5. Address ↔ Cluster binding
    # =====================================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS cluster_addresses (
        address TEXT PRIMARY KEY,
        cluster_id INTEGER,
        confidence REAL DEFAULT 0.0,
        first_seen INTEGER,
        last_seen INTEGER,
        FOREIGN KEY(cluster_id) REFERENCES clusters(id)
    )
    """)

    # =====================================================
    # 6. Whale classification (final interpretation layer)
    # =====================================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS whale_classification (
        txid TEXT PRIMARY KEY,
        btc REAL,
        time INTEGER,

        from_cluster INTEGER,
        to_cluster INTEGER,

        flow_type TEXT DEFAULT 'UNKNOWN',   -- DEPOSIT / WITHDRAW / INTERNAL / UNKNOWN

        FOREIGN KEY(from_cluster) REFERENCES clusters(id),
        FOREIGN KEY(to_cluster) REFERENCES clusters(id)
    )
    """)

    # =====================================================
    # 7. Exchange Flow Aggregation
    # =====================================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS exchange_flow (
        ts INTEGER,
        cluster_id INTEGER,
        flow_type TEXT,          -- DEPOSIT / WITHDRAW
        btc REAL,
        PRIMARY KEY (ts, cluster_id, flow_type),
        FOREIGN KEY(cluster_id) REFERENCES clusters(id)
    )
    """)

    # =====================================================
    # 8. Behavioral statistics
    # =====================================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS address_behavior (
        address TEXT PRIMARY KEY,
        avg_tx_value REAL DEFAULT 0,
        max_tx_value REAL DEFAULT 0,
        unique_counterparties INTEGER DEFAULT 0,
        rapid_tx_count INTEGER DEFAULT 0,
        FOREIGN KEY(address) REFERENCES addresses(address)
    )
    """)

    # =====================================================
    # 9. Whale correlation learning
    # =====================================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS whale_correlation (
        window INTEGER PRIMARY KEY,
        weight REAL,
        samples INTEGER
    )
    """)

    # =====================================================
    # 10. BTC price history
    # =====================================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS btc_price (
        ts INTEGER PRIMARY KEY,
        price REAL
    )
    """)

    # =====================================================
    # SEED EXCHANGE CLUSTERS (ANCHORS)
    # =====================================================

    anchors = [
        # BINANCE
        ('bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh', 'Binance'),
        ('bc1q0e0g9s7n6yd9e5n6g6n2p9n7w6g2g7p7y9kz9f', 'Binance'),

        # COINBASE
        ('bc1qz5h7d0y8m4c9p8g6e3x0k9r7l5v6t4s3n2a1q0', 'Coinbase'),

        # KRAKEN
        ('1Kraken4x3kJp9H5e5mZ6T7N8B4QWJf6', 'Kraken'),

        # BITFINEX
        ('1BitfiNexColdWalletX93P7kT3', 'Bitfinex'),

        # BITSTAMP
        ('1BitstampVaultMainCold123', 'Bitstamp'),
    ]

    import time
    now = int(time.time())

    for addr, exch in anchors:
        # 1. create exchange cluster if not exists
        c.execute("""
        INSERT OR IGNORE INTO clusters
        (cluster_type, name, subtype, confidence, size, created_at, last_updated)
        VALUES ('EXCHANGE', ?, 'COLD', 1.0, 1, ?, ?)
        """, (exch, now, now))

        # 2. get cluster id
        c.execute("""
        SELECT id FROM clusters
        WHERE cluster_type='EXCHANGE' AND name=?
        """, (exch,))
        cluster_id = c.fetchone()["id"]

        # 3. bind anchor address
        c.execute("""
        INSERT OR IGNORE INTO cluster_addresses
        (address, cluster_id, confidence, first_seen, last_seen)
        VALUES (?, ?, 1.0, ?, ?)
        """, (addr, cluster_id, now, now))

    conn.commit()
    conn.close()