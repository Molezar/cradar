# services/indicators/trend/ema.py
from services.indicators.base import IndicatorSignal
from database.database import get_db

EMA_FAST = 20
EMA_SLOW = 50


def calculate_ema(prices, period):
    multiplier = 2 / (period + 1)
    ema = prices[-period]  # стартовая точка

    for price in prices[-period+1:]:
        ema = (price - ema) * multiplier + ema

    return ema


async def get_ema_signal(price):
    conn = None
    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT close
            FROM btc_candles_1m
            ORDER BY open_time DESC
            LIMIT ?
        """, (EMA_SLOW + 5,)).fetchall()

        closes = [r["close"] for r in rows]

    finally:
        if conn:
            conn.close()

    if len(closes) < EMA_SLOW:
        return IndicatorSignal("EMA", "NEUTRAL", 0, 0)

    closes = list(reversed(closes))  # старые → новые

    ema_fast = calculate_ema(closes, EMA_FAST)
    ema_slow = calculate_ema(closes, EMA_SLOW)

    direction = "LONG" if ema_fast > ema_slow else "SHORT"
    strength = (ema_fast - ema_slow) / ema_slow
    confidence = min(abs(strength) * 20, 1)

    return IndicatorSignal(
        name="EMA",
        direction=direction,
        strength=strength,
        confidence=confidence,
        meta={"ema_fast": ema_fast, "ema_slow": ema_slow}
    )