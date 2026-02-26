DEFAULT_LEVERAGE = 5

def build_trade(signal_data, price):

    direction = signal_data["direction"]

    if direction == "LONG":
        stop = price * 0.98
        take = price * 1.04
    else:
        stop = price * 1.02
        take = price * 0.96

    return direction, price, stop, take, DEFAULT_LEVERAGE