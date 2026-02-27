# services/indicators/trend/ema.py
from services.indicators.base import IndicatorSignal

EMA_FAST = 20
EMA_SLOW = 50


def calculate_ema(prices, period):
    """
    Правильный EMA:
    1. Начинаем с SMA первых period значений
    2. Затем считаем EMA по всей серии
    """

    if len(prices) < period:
        return None

    multiplier = 2 / (period + 1)

    # стартовая EMA = SMA первых period свечей
    sma = sum(prices[:period]) / period
    ema = sma

    # продолжаем по остальным данным
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema

    return ema


def get_ema_signal(candles):
    closes = [float(c["close"]) for c in candles]

    if len(closes) < EMA_SLOW:
        return IndicatorSignal("EMA", "NEUTRAL", 0, 0)

    ema_fast = calculate_ema(closes, EMA_FAST)
    ema_slow = calculate_ema(closes, EMA_SLOW)

    if ema_fast is None or ema_slow is None:
        return IndicatorSignal("EMA", "NEUTRAL", 0, 0)

    direction = "LONG" if ema_fast > ema_slow else "SHORT"

    strength = (ema_fast - ema_slow) / ema_slow
    confidence = min(abs(strength) * 20, 1)

    return IndicatorSignal(
        name="EMA",
        direction=direction,
        strength=strength,
        confidence=confidence,
        meta={
            "ema_fast": ema_fast,
            "ema_slow": ema_slow
        }
    )