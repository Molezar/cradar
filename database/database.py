# database.py
import sqlite3
from pathlib import Path
from config import Config
import time

DB_PATH = Path(Config.DB_PATH)

def get_db(as_dict=True, retries=10, delay=0.3):

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
            conn.execute("PRAGMA busy_timeout=10000;")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA temp_store = MEMORY;")
            conn.execute("PRAGMA mmap_size = 1000000000;")

            return conn

        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                time.sleep(delay)
            else:
                raise

    raise Exception("Database is locked after retries")

def init_db():
    print("Python sqlite3 module version:", sqlite3.version)
    print("SQLite library version:", sqlite3.sqlite_version)

    conn = get_db()
    c = conn.cursor()
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute("PRAGMA synchronous=NORMAL;")

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
    
    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_tx_outputs_txid_addr
    ON tx_outputs(txid, address)
    """)
    
    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_tx_inputs_txid_addr
    ON tx_inputs(txid, address)
    """)

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
    # Address fingerprint
    # =====================================================
    c.execute("""
    CREATE TABLE IF NOT EXISTS address_fingerprint (
        prefix TEXT,
        length INTEGER,
        cluster_id INTEGER,
        count INTEGER,
        PRIMARY KEY(prefix,length,cluster_id),
        FOREIGN KEY(cluster_id) REFERENCES clusters(id)
    )
    """)
    
    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_address_fingerprint_prefix
    ON address_fingerprint(prefix)
    """)
    
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
    ON whale_classification(time)
    """)

    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_whale_time_flow
    ON whale_classification(time, flow_type)
    """)
    
    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_whale_from_cluster_time
    ON whale_classification(from_cluster, time)
    """)
    
    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_whale_to_cluster_time
    ON whale_classification(to_cluster, time)
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
    
    conn.commit()
    conn.close()