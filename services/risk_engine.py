#services/risk_engine.py
DEFAULT_LEVERAGE = 7

def build_trade(signal_data, price, base_leverage=5):
    direction = signal_data["direction"]
    score = abs(signal_data["score"])
    volatility = signal_data.get("volatility", 0)

    # Левередж умеренный
    leverage = min(max(3, base_leverage), 7)

    stop_buffer = 0.004 + volatility / 7000
    take_buffer = 0.012 + score * 0.001
    
    if direction == "LONG":
        stop = price * (1 - stop_buffer)
        take = price * (1 + take_buffer)
    else:
        stop = price * (1 + stop_buffer)
        take = price * (1 - take_buffer)

    return direction, price, stop, take, leverage