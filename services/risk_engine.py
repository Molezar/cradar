#services/risk_engine.py
DEFAULT_LEVERAGE = 5
    
def build_trade(signal_data, price, base_leverage=5):
    direction = signal_data["direction"]
    score = signal_data["score"]
    volatility = signal_data.get("volatility", 0)

    # Динамический левередж: чем выше уверенность, тем выше левередж
    leverage = max(1, min(base_leverage * abs(score), 10))

    # Стоп и тейк с учётом волатильности
    stop_buffer = 0.02 + volatility / 1000
    take_buffer = 0.04 + volatility / 1000 + 0.05 * max(0, score-0.5)

    if direction == "LONG":
        stop = price * (1 - stop_buffer)
        take = price * (1 + take_buffer)
    else:
        stop = price * (1 + stop_buffer)
        take = price * (1 - take_buffer)

    return direction, price, stop, take, leverage