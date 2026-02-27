# services/indicators/timing/rsi.py
from services.indicators.base import IndicatorSignal
from database.database import get_db

RSI_PERIOD = 7


async def get_rsi_signal(price, period=RSI_PERIOD):
    conn = None
    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT close
            FROM btc_candles_1m
            ORDER BY open_time DESC
            LIMIT ?
        """, (period + 1,)).fetchall()

        closes = [r["close"] for r in rows]

    finally:
        if conn:
            conn.close()

    if len(closes) < period + 1:
        return IndicatorSignal("RSI", "NEUTRAL", 0, 0)

    closes = list(reversed(closes))

    gains = []
    losses = []

    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        rsi = 100
    else:
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

    if rsi < 30:
        direction = "LONG"
    elif rsi > 70:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    strength = abs(rsi - 50) / 50
    confidence = strength

    return IndicatorSignal(
        "RSI",
        direction,
        strength if direction != "NEUTRAL" else 0,
        confidence,
        meta={"rsi": rsi}
    )