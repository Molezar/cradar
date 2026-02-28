#services/risk_engine.py
DEFAULT_LEVERAGE = 5

def build_trade(signal_data, price, base_leverage=5):
    direction = signal_data["direction"]
    score = abs(signal_data["score"])
    volatility = signal_data.get("volatility", 0)

    # Левередж умеренный
    leverage = min(max(3, base_leverage), 7)

    # Короткие intraday буферы
    stop_buffer = 0.005 + volatility / 5000   # ~0.5–1%
    take_buffer = 0.008 + score * 0.001        # 0.8–1.5%

    if direction == "LONG":
        stop = price * (1 - stop_buffer)
        take = price * (1 + take_buffer)
    else:
        stop = price * (1 + stop_buffer)
        take = price * (1 - take_buffer)

    return direction, price, stop, take, leverage