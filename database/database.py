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

    # Whale txs
    c.execute("""
    CREATE TABLE IF NOT EXISTS whale_tx (
        txid TEXT PRIMARY KEY,
        btc REAL,
        time INTEGER
    )
    """)

    # Addresses
    c.execute("""
    CREATE TABLE IF NOT EXISTS addresses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        address TEXT UNIQUE,
        first_seen INTEGER,
        last_seen INTEGER,
        total_btc REAL DEFAULT 0
    )
    """)

    # Outputs
    c.execute("""
    CREATE TABLE IF NOT EXISTS tx_outputs (
        txid TEXT,
        address TEXT,
        btc REAL
    )
    """)

    # BTC price history
    c.execute("""
    CREATE TABLE IF NOT EXISTS btc_price (
        ts INTEGER PRIMARY KEY,
        price REAL
    )
    """)

    # Aggregated whale flow per window
    c.execute("""
    CREATE TABLE IF NOT EXISTS whale_flow (
        ts INTEGER PRIMARY KEY,
        total_btc REAL
    )
    """)

    # Learned correlations
    c.execute("""
    CREATE TABLE IF NOT EXISTS whale_correlation (
        window INTEGER PRIMARY KEY,
        weight REAL,
        samples INTEGER
    )
    """)

    conn.commit()
    conn.close()