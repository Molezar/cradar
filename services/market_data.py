#services/market_data.py
from database.database import get_db


async def get_market_candles(limit=100):
    conn = None
    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT open_time, open, high, low, close, volume
            FROM btc_candles_1m
            ORDER BY open_time DESC
            LIMIT ?
        """, (limit,)).fetchall()

        return list(reversed([dict(r) for r in rows]))

    finally:
        if conn:
            conn.close()