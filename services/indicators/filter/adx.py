# services/indicators/filter/adx.py
from services.indicators.base import IndicatorSignal
from database.database import get_db

async def get_adx_signal(price, period=14):
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
        return IndicatorSignal("ADX", "NEUTRAL", 0, 0)

    highs = prices[:-1]
    lows = prices[1:]
    tr = [abs(highs[i]-lows[i]) for i in range(len(highs))]
    atr = sum(tr)/len(tr)

    adx_value = atr / (sum(prices)/len(prices))  # упрощённый ADX proxy
    confidence = min(adx_value * 5, 1.0)

    return IndicatorSignal(
        name="ADX",
        direction="NEUTRAL",
        strength=0,
        confidence=confidence,
        meta={"adx": adx_value}
    )