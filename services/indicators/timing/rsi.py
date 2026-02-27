# services/indicators/trend/rsi.py
from services.indicators.base import IndicatorSignal

RSI_PERIOD = 7


def get_rsi_signal(candles, period=RSI_PERIOD):
    closes = [float(c["close"]) for c in candles]

    if len(closes) < period + 1:
        return IndicatorSignal("RSI", "NEUTRAL", 0, 0)

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
        name="RSI",
        direction=direction,
        strength=strength if direction != "NEUTRAL" else 0,
        confidence=confidence,
        meta={"rsi": rsi}
    )