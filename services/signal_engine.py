# services/signal_engine.py
from services.indicators.base import IndicatorSignal
from services.indicators.prediction import get_prediction_signal
from services.indicators.trend.ma import get_ma_signal
from services.indicators.trend.ema import get_ema_signal
from services.indicators.timing.rsi import get_rsi_signal
from services.indicators.filter.adx import get_adx_signal
from database.database import get_db
import math
from logger import get_logger
logger = get_logger(__name__)

VOLATILITY_FACTOR = 1.0  # можно менять, чтобы усилить/ослабить влияние волатильности на сигнал

async def collect_indicators(price):
    signals = []

    # --- Trend ---
    ema_signal = await get_ema_signal(price)
    if ema_signal:
        signals.append(ema_signal)

    ma_signal = await get_ma_signal(price)
    if ma_signal:
        signals.append(ma_signal)

    # --- Timing ---
    rsi_signal = await get_rsi_signal(price)
    if rsi_signal:
        signals.append(rsi_signal)

    # --- Filter ---
    adx_signal = await get_adx_signal(price)
    if adx_signal:
        signals.append(adx_signal)

    # --- Volatility as filter ---
    volatility_value = compute_volatility()
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


def compute_volatility(window=50):
    """Возвращает стандартное отклонение цен за последнее окно"""
    conn = None
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT price FROM btc_price ORDER BY ts DESC LIMIT ?", (window,)
        ).fetchall()
        prices = [r["price"] for r in rows]
        if len(prices) < 2:
            return 0
        mean = sum(prices) / len(prices)
        variance = sum((p - mean) ** 2 for p in prices) / len(prices)
        return math.sqrt(variance)
    finally:
        if conn:
            conn.close()

def aggregate_signals(signals):
    logger.info("---- AGGREGATE START ----")

    for s in signals:
        logger.info(
            f"[{s.name}] "
            f"dir={s.direction} "
            f"strength={s.strength} "
            f"confidence={s.confidence} "
            f"score={s.score()}"
        )

    trend_signals = [s for s in signals if s.name in ["EMA", "MA_CROSS"]]
    filter_signals = [s for s in signals if s.name in ["ADX", "VOLATILITY"]]
    timing_signals = [s for s in signals if s.name in ["RSI"]]

    if not trend_signals:
        logger.info("No trend signals → returning None")
        return None

    total_score = sum(s.score() for s in trend_signals)
    logger.info(f"Trend score sum: {total_score}")

    # фильтры
    for s in filter_signals:
        logger.info(f"Applying filter {s.name} with confidence {s.confidence}")
        total_score *= s.confidence

    # тайминг
    for s in timing_signals:
        logger.info(f"Applying timing {s.name} with confidence {s.confidence}")
        total_score *= s.confidence

    vol_signal = next((s for s in signals if s.name == "VOLATILITY"), None)
    volatility = vol_signal.meta.get("volatility") if vol_signal else 0

    base_threshold = 0.15
    threshold = base_threshold + volatility / 1000

    logger.info(f"Final total_score: {total_score}")
    logger.info(f"Threshold: {threshold}")
    logger.info(f"Volatility: {volatility}")

    if abs(total_score) < threshold:
        logger.info("Score below threshold → FLAT")
        logger.info("---- AGGREGATE END ----")
        return None

    direction = "LONG" if total_score > 0 else "SHORT"

    logger.info(f"FINAL SIGNAL: {direction}")
    logger.info("---- AGGREGATE END ----")

    return {
        "direction": direction,
        "score": total_score,
        "signals": signals,
        "volatility": volatility,
        "threshold": threshold
    }
