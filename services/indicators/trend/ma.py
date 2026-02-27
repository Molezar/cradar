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
            SELECT close
            FROM btc_candles_1m
            ORDER BY open_time DESC
            LIMIT ?
        """, (SLOW_PERIOD,)).fetchall()

        if len(rows) < SLOW_PERIOD:
            return None

        closes = [r["close"] for r in rows]
        closes = list(reversed(closes))

        fast_sma = calculate_sma(closes[-FAST_PERIOD:])
        slow_sma = calculate_sma(closes)

        if fast_sma > slow_sma:
            direction = "LONG"
        elif fast_sma < slow_sma:
            direction = "SHORT"
        else:
            return None

        spread = abs(fast_sma - slow_sma) / slow_sma
        strength = min(spread * 15, 1.0)
        confidence = min(spread * 20, 1.0)

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