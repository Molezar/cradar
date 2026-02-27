# services/indicators/timing/rsi.py
from services.indicators.base import IndicatorSignal
from database.database import get_db

async def get_rsi_signal(price, period=7):
    conn = None
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT price FROM btc_price ORDER BY ts DESC LIMIT ?", (period+1,)
        ).fetchall()
        prices = [r["price"] for r in rows]
    finally:
        if conn:
            conn.close()

    if len(prices) < period:
        return IndicatorSignal("RSI", "NEUTRAL", 0, 0)

    gains = sum(max(prices[i] - prices[i+1], 0) for i in range(period))
    losses = sum(max(prices[i+1] - prices[i], 0) for i in range(period))
    rs = gains / losses if losses != 0 else 0
    rsi = 100 - (100 / (1 + rs))

    if rsi < 30:
        direction = "LONG"
    elif rsi > 70:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    strength = 1 if direction != "NEUTRAL" else 0
    confidence = abs(rsi-50)/50  # ближе к 0-50-100

    return IndicatorSignal("RSI", direction, strength, confidence)