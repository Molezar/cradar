# services/indicators/trend/ema.py
from services.indicators.base import IndicatorSignal
from database.database import get_db

async def get_ema_signal(price):
    conn = None
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT price FROM btc_price ORDER BY ts DESC LIMIT 50"
        ).fetchall()
        prices = [r["price"] for r in rows]
    finally:
        if conn:
            conn.close()

    if len(prices) < 20:
        return IndicatorSignal("EMA", "NEUTRAL", 0, 0)

    ema20 = sum(prices[:20]) / 20
    ema50 = sum(prices[:50]) / 50

    direction = "LONG" if ema20 > ema50 else "SHORT"
    strength = (ema20 - ema50) / ema50
    confidence = min(abs(strength) * 10, 1)

    return IndicatorSignal(
        name="EMA",
        direction=direction,
        strength=strength,
        confidence=confidence,
        meta={"ema20": ema20, "ema50": ema50}
    )