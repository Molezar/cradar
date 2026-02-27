#services/market_data.py
from config import Config
from services.candles import get_candles
from database.database import get_db


async def get_market_candles(limit=100):
    """
    Возвращает список свечей:
    [
        {
            "open_time": int,
            "open": float,
            "high": float,
            "low": float,
            "close": float,
            "volume": float
        }
    ]
    """

    if Config.USE_API_CANDLES:
        return await get_candles(limit)

    # ---- прямой доступ к БД ----
    conn = None
    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT open_time, open, high, low, close, volume
            FROM btc_candles_1m
            ORDER BY open_time DESC
            LIMIT ?
        """, (limit,)).fetchall()

        return [dict(r) for r in rows]

    finally:
        if conn:
            conn.close()