# services/indicators/filter/adx.py
from services.indicators.base import IndicatorSignal
from database.database import get_db

ADX_PERIOD = 14


async def get_adx_signal(price, period=ADX_PERIOD):
    conn = None
    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT high, low, close
            FROM btc_candles_1m
            ORDER BY open_time DESC
            LIMIT ?
        """, (period + 1,)).fetchall()

        candles = [dict(r) for r in rows]

    finally:
        if conn:
            conn.close()

    if len(candles) < period + 1:
        return IndicatorSignal("ADX", "NEUTRAL", 0, 0)

    candles = list(reversed(candles))

    tr_list = []
    plus_dm = []
    minus_dm = []

    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_high = candles[i - 1]["high"]
        prev_low = candles[i - 1]["low"]
        prev_close = candles[i - 1]["close"]

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        tr_list.append(tr)

        up_move = high - prev_high
        down_move = prev_low - low

        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0)

    atr = sum(tr_list[-period:]) / period
    plus_di = 100 * (sum(plus_dm[-period:]) / period) / atr if atr else 0
    minus_di = 100 * (sum(minus_dm[-period:]) / period) / atr if atr else 0

    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) else 0
    adx = dx  # упрощённая версия без сглаживания

    confidence = min(adx / 50, 1.0)

    return IndicatorSignal(
        name="ADX",
        direction="NEUTRAL",
        strength=0,
        confidence=confidence,
        meta={"adx": adx}
    )