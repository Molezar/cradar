# services/indicators/trend/ma.py
from database.database import get_db
from services.indicators.base import IndicatorSignal

FAST_PERIOD = 20
SLOW_PERIOD = 50

def calculate_sma(prices):
    return sum(prices) / len(prices)

async def get_ma_signal(price: float):
    conn = None
    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT price
            FROM btc_price
            ORDER BY ts DESC
            LIMIT ?
        """, (SLOW_PERIOD,)).fetchall()

        if len(rows) < SLOW_PERIOD:
            return None

        prices = [r["price"] for r in rows]
        fast_sma = calculate_sma(prices[:FAST_PERIOD])
        slow_sma = calculate_sma(prices[:SLOW_PERIOD])

        if fast_sma > slow_sma:
            direction = "LONG"
        elif fast_sma < slow_sma:
            direction = "SHORT"
        else:
            return None

        spread = abs(fast_sma - slow_sma) / slow_sma
        strength = min(spread * 10, 1.0)
        confidence = min(spread * 15, 1.0)

        return IndicatorSignal(
            name="MA_CROSS",
            direction=direction,
            strength=strength,
            confidence=confidence,
            meta={"fast_sma": fast_sma, "slow_sma": slow_sma}
        )

    finally:
        if conn:
            conn.close()