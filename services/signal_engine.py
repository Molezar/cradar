from services.indicators.prediction import get_prediction_signal
# позже добавишь:
# from services.indicators.ma import get_ma_signal
# from services.indicators.macd import get_macd_signal

async def collect_indicators(price):

    signals = []

    signals.append(await get_prediction_signal(price))

    # signals.append(await get_ma_signal(price))
    # signals.append(await get_macd_signal(price))

    return signals


def aggregate_signals(signals):

    total_score = 0

    for s in signals:
        total_score += s.score()

    if abs(total_score) < 0.2:
        return None

    direction = "LONG" if total_score > 0 else "SHORT"

    return {
        "direction": direction,
        "score": total_score,
        "signals": signals
    }