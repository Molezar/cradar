# services/indicators/trend/adx.py
from services.indicators.base import IndicatorSignal

ADX_PERIOD = 14


def get_adx_signal(candles, period=ADX_PERIOD):
    if len(candles) < period + 1:
        return IndicatorSignal("ADX", "NEUTRAL", 0, 0)

    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    closes = [float(c["close"]) for c in candles]

    tr_list = []
    plus_dm = []
    minus_dm = []

    for i in range(1, len(candles)):
        high = highs[i]
        low = lows[i]
        prev_high = highs[i - 1]
        prev_low = lows[i - 1]
        prev_close = closes[i - 1]

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
    adx = dx  # упрощённая версия

    confidence = min(adx / 50, 1.0)

    return IndicatorSignal(
        name="ADX",
        direction="NEUTRAL",
        strength=0,
        confidence=confidence,
        meta={
            "adx": adx,
            "plus_di": plus_di,
            "minus_di": minus_di
        }
    )