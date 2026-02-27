# services/indicators/trend/ma.py
from services.indicators.base import IndicatorSignal

FAST_PERIOD = 20
SLOW_PERIOD = 50


def calculate_sma(prices):
    return sum(prices) / len(prices)


def get_ma_signal(candles):
    closes = [float(c["close"]) for c in candles]

    if len(closes) < SLOW_PERIOD:
        return IndicatorSignal("MA_CROSS", "NEUTRAL", 0, 0)

    fast_sma = calculate_sma(closes[-FAST_PERIOD:])
    slow_sma = calculate_sma(closes[-SLOW_PERIOD:])

    if fast_sma > slow_sma:
        direction = "LONG"
    elif fast_sma < slow_sma:
        direction = "SHORT"
    else:
        return IndicatorSignal("MA_CROSS", "NEUTRAL", 0, 0)

    spread = abs(fast_sma - slow_sma) / slow_sma
    strength = min(spread * 15, 1.0)
    confidence = min(spread * 20, 1.0)

    return IndicatorSignal(
        name="MA_CROSS",
        direction=direction,
        strength=strength,
        confidence=confidence,
        meta={
            "fast_sma": fast_sma,
            "slow_sma": slow_sma
        }
    )