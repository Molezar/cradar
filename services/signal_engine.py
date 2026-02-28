# services/signal_engine.py
import math
from services.indicators.base import IndicatorSignal
from services.indicators.prediction import get_prediction_signal
from services.indicators.trend.ma import get_ma_signal
from services.indicators.trend.ema import get_ema_signal
from services.indicators.timing.rsi import get_rsi_signal
from services.indicators.filter.adx import get_adx_signal
from logger import get_logger

logger = get_logger(__name__)

VOLATILITY_FACTOR = 1.0  # можно менять, чтобы усилить/ослабить влияние волатильности на сигнал

def collect_indicators(candles):
    signals = []
    
    # --- Trend ---
    ema_signal = get_ema_signal(candles)
    if ema_signal:
        signals.append(ema_signal)

    ma_signal = get_ma_signal(candles)
    if ma_signal:
        signals.append(ma_signal)

    # --- Timing ---
    rsi_signal = get_rsi_signal(candles)
    if rsi_signal:
        signals.append(rsi_signal)

    # --- Filter ---
    adx_signal = get_adx_signal(candles)
    if adx_signal:
        signals.append(adx_signal)

    # --- Volatility as filter ---
    volatility_value = compute_volatility(candles)
    volatility_confidence = min(volatility_value / 1000 * VOLATILITY_FACTOR, 1.0)
    volatility_signal = IndicatorSignal(
        name="VOLATILITY",
        direction="NEUTRAL",
        strength=0,
        confidence=volatility_confidence,
        meta={"volatility": volatility_value}
    )
    signals.append(volatility_signal)

    # --- Prediction (можно отключить) ---
    # prediction = await get_prediction_signal(price)
    # if prediction:
    #     signals.append(prediction)

    return signals
    
def compute_volatility(candles, window=50):
    closes = [float(c["close"]) for c in candles[-window:]]

    if len(closes) < 2:
        return 0

    mean = sum(closes) / len(closes)
    variance = sum((c - mean) ** 2 for c in closes) / len(closes)

    return math.sqrt(variance)

def aggregate_signals(signals):
    logger.info("---- AGGREGATE START (WEIGHTED MODEL) ----")

    for s in signals:
        logger.info(
            f"[{s.name}] "
            f"dir={s.direction} "
            f"strength={s.strength} "
            f"confidence={s.confidence} "
            f"score={s.score()}"
        )

    trend_signals = [s for s in signals if s.name in ["EMA", "MA_CROSS"]]
    rsi_signal = next((s for s in signals if s.name == "RSI"), None)
    adx_signal = next((s for s in signals if s.name == "ADX"), None)
    vol_signal = next((s for s in signals if s.name == "VOLATILITY"), None)

    if not trend_signals:
        logger.info("No trend signals → returning None")
        return None

    # --- TREND SCORE (среднее, чтобы не раздувать если 2 индикатора) ---
    trend_score = sum(s.score() for s in trend_signals) / len(trend_signals)
    logger.info(f"Trend score: {trend_score}")

    # --- RSI SCORE ---
    rsi_score = rsi_signal.score() if rsi_signal else 0
    logger.info(f"RSI score: {rsi_score}")

    # --- ADX SCORE ---
    adx_score = adx_signal.confidence if adx_signal else 0
    logger.info(f"ADX score: {adx_score}")

    # --- WEIGHTED MODEL ---
    total_score = (
        trend_score * 0.6 +
        rsi_score   * 0.2 +
        adx_score   * 0.2
    )

    logger.info(f"Weighted score before volatility: {total_score}")

    # --- VOLATILITY MULTIPLIER ---
    volatility = vol_signal.meta.get("volatility") if vol_signal else 0
    logger.info(f"Volatility: {volatility}")

    volatility_multiplier = min(volatility / 100, 2)
    total_score *= volatility_multiplier

    # Масштабируем score
    total_score *= 100
    
    logger.info(f"Final total_score: {total_score}")

    if total_score > 0:
        direction = "LONG"
    elif total_score < 0:
        direction = "SHORT"
    else:
        return None

    logger.info(f"FINAL SIGNAL: {direction}")
    logger.info("---- AGGREGATE END ----")

    return {
        "direction": direction,
        "score": total_score,
        "signals": signals,
        "volatility": volatility
    }