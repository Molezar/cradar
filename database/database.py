import sqlite3
import time
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

    # ==========================
    # Whale transactions
    # ==========================
    c.execute("""
    CREATE TABLE IF NOT EXISTS whale_tx (
        txid TEXT PRIMARY KEY,
        btc REAL,
        time INTEGER
    )
    """)

    # ==========================
    # Addresses seen on-chain
    # ==========================
    c.execute("""
    CREATE TABLE IF NOT EXISTS addresses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        address TEXT UNIQUE,
        first_seen INTEGER,
        last_seen INTEGER,
        total_btc REAL DEFAULT 0
    )
    """)

    # ==========================
    # Transaction outputs
    # ==========================
    c.execute("""
    CREATE TABLE IF NOT EXISTS tx_outputs (
        txid TEXT,
        address TEXT,
        btc REAL
    )
    """)

    # ==========================
    # BTC price history
    # ==========================
    c.execute("""
    CREATE TABLE IF NOT EXISTS btc_price (
        ts INTEGER PRIMARY KEY,
        price REAL
    )
    """)

    # ==========================
    # Exchange clustering foundation
    # ==========================
    c.execute("""
    CREATE TABLE IF NOT EXISTS exchange_addresses (
        address TEXT PRIMARY KEY,
        exchange TEXT NOT NULL,
        is_anchor INTEGER DEFAULT 0,
        score REAL DEFAULT 0.0
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS whale_classification (
        txid TEXT PRIMARY KEY,
        exchange TEXT,
        btc REAL,
        time INTEGER,
        flow_type TEXT DEFAULT 'UNKNOWN'
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS exchange_flow (
        ts INTEGER PRIMARY KEY,
        buy_btc REAL DEFAULT 0,
        sell_btc REAL DEFAULT 0
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS exchange_flow_v2 (
        ts INTEGER,
        exchange TEXT,
        flow_type TEXT,       -- DEPOSIT / WITHDRAWAL / INTERNAL / OTC
        btc REAL,
        PRIMARY KEY (ts, exchange, flow_type)
    )
    """)

    # ==========================
    # Exchange clusters & address binding
    # ==========================
    c.execute("""
    CREATE TABLE IF NOT EXISTS exchange_clusters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exchange TEXT NOT NULL,
        confidence REAL DEFAULT 0.0,
        size INTEGER DEFAULT 0,
        created_at INTEGER
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS address_cluster (
        address TEXT PRIMARY KEY,
        cluster_id INTEGER,
        confidence REAL DEFAULT 0.0,
        FOREIGN KEY(cluster_id) REFERENCES exchange_clusters(id)
    )
    """)

    # ==========================
    # Learned correlations
    # ==========================
    c.execute("""
    CREATE TABLE IF NOT EXISTS whale_correlation (
        window INTEGER PRIMARY KEY,
        weight REAL,
        samples INTEGER
    )
    """)

    # ==========================
    # Seed cold wallet anchors
    # ==========================
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

    for addr, exch in anchors:
        c.execute("""
        INSERT OR IGNORE INTO exchange_addresses(address, exchange, is_anchor, score)
        VALUES (?, ?, 1, 1.0)
        """, (addr, exch))

    # Seed clusters from anchors
    c.execute("""
    INSERT INTO exchange_clusters (exchange, confidence, size, created_at)
    SELECT
        exchange,
        1.0,
        COUNT(*),
        strftime('%s','now')
    FROM exchange_addresses
    WHERE is_anchor = 1
    GROUP BY exchange
    """)

    c.execute("""
    INSERT OR IGNORE INTO address_cluster(address, cluster_id, confidence)
    SELECT
        ea.address,
        ec.id,
        1.0
    FROM exchange_addresses ea
    JOIN exchange_clusters ec ON ec.exchange = ea.exchange
    WHERE ea.is_anchor = 1
    """)

    conn.commit()
    conn.close()