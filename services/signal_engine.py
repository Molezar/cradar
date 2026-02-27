# services/signal_engine.py
from services.indicators.base import IndicatorSignal
from services.indicators.prediction import get_prediction_signal
from services.indicators.trend.ma import get_ma_signal
from services.indicators.trend.ema import get_ema_signal
from services.indicators.timing.rsi import get_rsi_signal
from services.indicators.filter.adx import get_adx_signal
from database.database import get_db
import math
from services.market_data import get_market_candles
from config import Config
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
    """
    Стандартное отклонение закрытий свечей
    """

    conn = None

    if Config.USE_API_CANDLES:
        # В async нельзя await здесь, поэтому volatility оставим DB-based
        # API режим будет использовать уже записанные свечи
        pass

    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT close FROM btc_candles_1m
            ORDER BY open_time DESC
            LIMIT ?
        """, (window,)).fetchall()

        closes = [r["close"] for r in rows]

        if len(closes) < 2:
            return 0

        mean = sum(closes) / len(closes)
        variance = sum((c - mean) ** 2 for c in closes) / len(closes)

        return math.sqrt(variance)

    finally:
        if conn:
            conn.close()

def aggregate_signals(signals):
    logger.info("---- AGGREGATE START (INTRADAY MODE) ----")

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

    total_score = sum(s.score() for s in trend_signals)
    logger.info(f"Trend score sum: {total_score}")

    # --- ADX пороговый фильтр ---
    if adx_signal:
        logger.info(f"ADX confidence: {adx_signal.confidence}")
        if adx_signal.confidence < 0.01:
            logger.info("ADX too weak → FLAT")
            return None

    # --- RSI должен подтверждать направление ---
    if rsi_signal and rsi_signal.direction != "NEUTRAL":
        logger.info("RSI confirms direction")
        total_score *= 1.2
    else:
        logger.info("RSI neutral → small penalty")
        total_score *= 0.8

    # --- Volatility минимальный фильтр ---
    volatility = vol_signal.meta.get("volatility") if vol_signal else 0
    logger.info(f"Volatility: {volatility}")

    if volatility < 20:
        logger.info("Volatility too low → FLAT")
        return None

    # --- intraday threshold ---
    threshold = 0.02
    logger.info(f"Final total_score: {total_score}")
    logger.info(f"Threshold: {threshold}")

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