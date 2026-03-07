#services/risk_engine.py
DEFAULT_LEVERAGE = 7

def build_trade(signal_data, price, base_leverage=5):
    direction = signal_data["direction"]
    # Используем raw_score (до умножения на 100)
    raw_score = abs(signal_data.get("raw_score", signal_data.get("score", 0) / 100))
    volatility = signal_data.get("volatility", 0)

    leverage = min(max(3, base_leverage), 7)

    stop_buffer = 0.004 + volatility / 7000
    take_buffer = 0.012 + raw_score * 0.001

    if direction == "LONG":
        stop = price * (1 - stop_buffer)
        take = price * (1 + take_buffer)
    else:
        stop = price * (1 + stop_buffer)
        take = price * (1 - take_buffer)

    return {
        "direction": direction,
        "entry": price,
        "stop": stop,
        "take": take,
        "leverage": leverage
    }