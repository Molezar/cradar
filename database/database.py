# database.py
import sqlite3
from pathlib import Path
from config import Config
import time

DB_PATH = Path(Config.DB_PATH)


def get_db(as_dict=True, retries=3, delay=0.3):

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(retries):
        try:
            conn = sqlite3.connect(
                DB_PATH,
                timeout=60,
                check_same_thread=False
            )
            if as_dict:
                conn.row_factory = sqlite3.Row
            else:
                conn.row_factory = None

            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.execute("PRAGMA foreign_keys = ON")

            return conn
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                time.sleep(delay)
            else:
                raise

    raise Exception("Database is locked after retries")


def init_db():
    conn = get_db()
    c = conn.cursor()

    # =====================================================
    # Whale TX
    # =====================================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS whale_tx (
        txid TEXT PRIMARY KEY,
        btc REAL NOT NULL,
        time INTEGER NOT NULL
    )
    """)

    # =====================================================
    # TX IO
    # =====================================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS tx_inputs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        txid TEXT,
        address TEXT,
        btc REAL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS tx_outputs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        txid TEXT,
        address TEXT,
        btc REAL
    )
    """)

    # Обычные индексы
    c.execute("CREATE INDEX IF NOT EXISTS idx_tx_inputs_txid ON tx_inputs(txid)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tx_outputs_txid ON tx_outputs(txid)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tx_inputs_addr ON tx_inputs(address)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tx_outputs_addr ON tx_outputs(address)")

    # 🔒 Защита от дублей IO (важно для INSERT OR IGNORE)
    c.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS ux_tx_inputs_unique
    ON tx_inputs(txid, address, btc)
    """)

    c.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS ux_tx_outputs_unique
    ON tx_outputs(txid, address, btc)
    """)

    # =====================================================
    # Clusters
    # =====================================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS clusters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cluster_type TEXT NOT NULL,
        name TEXT,
        subtype TEXT,
        confidence REAL DEFAULT 0.0,
        size INTEGER DEFAULT 0,
        created_at INTEGER,
        last_updated INTEGER
    )
    """)

    c.execute("CREATE INDEX IF NOT EXISTS idx_clusters_type ON clusters(cluster_type)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_clusters_name ON clusters(name)")

    # =====================================================
    # Cluster addresses
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

    c.execute("CREATE INDEX IF NOT EXISTS idx_cluster_addr_cluster ON cluster_addresses(cluster_id)")

    # =====================================================
    # Whale classification (flow-based)
    # =====================================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS whale_classification (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        txid TEXT,
        btc REAL,
        confidence REAL DEFAULT 0.7,
        time INTEGER,
        from_cluster INTEGER,
        to_cluster INTEGER,
        flow_type TEXT,
        FOREIGN KEY(from_cluster) REFERENCES clusters(id),
        FOREIGN KEY(to_cluster) REFERENCES clusters(id)
    )
    """)

    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_whale_time
    ON whale_classification(time DESC)
    """)

    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_whale_time_flow
    ON whale_classification(time, flow_type)
    """)

    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_whale_to_cluster
    ON whale_classification(to_cluster)
    """)

    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_whale_from_cluster
    ON whale_classification(from_cluster)
    """)

    # Защита от дублей flows
    c.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS ux_whale_unique_flow
    ON whale_classification(txid, flow_type, from_cluster, to_cluster)
    """)

    # =====================================================
    # Exchange Flow
    # =====================================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS exchange_flow (
        ts INTEGER,
        cluster_id INTEGER,
        flow_type TEXT,
        btc REAL,
        PRIMARY KEY (ts, cluster_id, flow_type),
        FOREIGN KEY(cluster_id) REFERENCES clusters(id)
    )
    """)

    c.execute("CREATE INDEX IF NOT EXISTS idx_exchange_flow_cluster ON exchange_flow(cluster_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_flow_ts ON exchange_flow(ts)")

    c.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS ux_exchange_flow_ts_cluster_flow
    ON exchange_flow(ts, cluster_id, flow_type)
    """)

    # =====================================================
    # Whale correlation
    # =====================================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS whale_correlation (
        window INTEGER PRIMARY KEY,
        weight REAL,
        samples INTEGER
    )
    """)

    # =====================================================
    # BTC price
    # =====================================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS btc_price (
        ts INTEGER PRIMARY KEY,
        price REAL
    )
    """)

    c.execute("CREATE INDEX IF NOT EXISTS idx_price_ts ON btc_price(ts)")

    # =====================================================
    # BTC candles
    # =====================================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS btc_candles_1m (
        open_time INTEGER PRIMARY KEY,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume REAL NOT NULL
    )
    """)

    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_btc_candles_1m_time
    ON btc_candles_1m(open_time)
    """)

    # =====================================================
    # Demo account
    # =====================================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS demo_account (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        balance REAL NOT NULL,
        updated_at INTEGER
    )
    """)

    c.execute("""
    INSERT OR IGNORE INTO demo_account (id, balance, updated_at)
    VALUES (1, 1000, strftime('%s','now'))
    """)

    # =====================================================
    # Trade signals
    # =====================================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS trade_signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at INTEGER,
        direction TEXT,
        entry REAL,
        stop REAL,
        take REAL,
        leverage INTEGER DEFAULT 5,
        status TEXT DEFAULT 'OPEN',
        result REAL DEFAULT 0,
        position_size REAL DEFAULT 0
    )
    """)

    c.execute("CREATE INDEX IF NOT EXISTS idx_trade_status ON trade_signals(status)")

    # =====================================================
    # Bot settings
    # =====================================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS bot_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        auto_mode INTEGER DEFAULT 0
    )
    """)

    c.execute("""
    INSERT OR IGNORE INTO bot_settings (id, auto_mode)
    VALUES (1, 0)
    """)

    # =====================================================
    # Seed exchange anchors (cold wallets)
    # =====================================================
    anchors = [
        # BINANCE
        ('bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh', 'Binance'),
        ('bc1q0e0g9s7n6yd9e5n6g6n2p9n7w6g2g7p7y9kz9f', 'Binance'),
        ('bc1q8z3r2n4q9c5x6l8n2v8m4f0tq8p3k7m6u9e0d', 'Binance'),

        # COINBASE
        ('bc1qz5h7d0y8m4c9p8g6e3x0k9r7l5v6t4s3n2a1q0', 'Coinbase'),
        ('bc1qk0l9m8n7p6q5r4s3t2u1v0w9x8y7z6a5b4c3d', 'Coinbase'),

        # KRAKEN
        ('1Kraken4x3kJp9H5e5mZ6T7N8B4QWJf6', 'Kraken'),
        ('bc1qkrakenvault0n3x8z4m5g7p9k6l2a', 'Kraken'),

        # BITFINEX
        ('bc1qbitfinexvault0f3x8z4m5g7p9k6l2a', 'Bitfinex'),
        ('1BitfiNexColdWalletX93P7kT3', 'Bitfinex'),

        # BITSTAMP
        ('bc1qbitstampcold9n4m3x8z6k7p5g2l', 'Bitstamp'),
        ('1BitstampVaultMainCold123', 'Bitstamp'),
    ]

    now = int(time.time())

    # Вставляем анкеры в cluster_addresses как отдельные кластеры EXCHANGE
    for addr, exch in anchors:
        # создаем кластер, если его ещё нет
        c.execute("""
            SELECT id FROM clusters
            WHERE cluster_type='EXCHANGE' AND name=?
        """, (exch,))
        row = c.fetchone()
        if row:
            cluster_id = row["id"]
        else:
            c.execute("""
                INSERT INTO clusters
                (cluster_type, name, confidence, size, created_at, last_updated)
                VALUES ('EXCHANGE', ?, 1.0, 0, ?, ?)
            """, (exch, now, now))
            cluster_id = c.lastrowid

        # вставляем адрес анкера
        c.execute("""
            INSERT OR IGNORE INTO cluster_addresses
            (address, cluster_id, confidence, first_seen, last_seen)
            VALUES (?, ?, 1.0, ?, ?)
        """, (addr, cluster_id, now, now))

    # обновляем size кластеров после вставки анкеров
    c.execute("""
        UPDATE clusters
        SET size = (
            SELECT COUNT(*) FROM cluster_addresses WHERE cluster_id=clusters.id
        )
        WHERE cluster_type='EXCHANGE'
    """)
    
    conn.commit()
    conn.close()