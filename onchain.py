import requests
import time

# CoinGlass (бывш. Bybt) — бесплатный агрегированный inflow Binance
COINGLASS_URL = "https://open-api.coinglass.com/public/v2/indicator/exchange_netflow"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
}

def btc_inflow_last_minutes(minutes=60):
    """
    Возвращает чистый inflow BTC на Binance за период
    minutes = 60, 240, 1440 и т.д.
    CoinGlass сам агрегирует on-chain данные всех кошельков Binance
    """

    # CoinGlass работает по таймфреймам: 1h, 4h, 1d
    if minutes <= 60:
        interval = "1h"
    elif minutes <= 240:
        interval = "4h"
    else:
        interval = "1d"

    params = {
        "symbol": "BTC",
        "exchange": "Binance",
        "interval": interval
    }

    try:
        r = requests.get(COINGLASS_URL, params=params, headers=HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()

        # структура:
        # data["data"][0]["inflow"], ["outflow"]
        d = data["data"][0]

        inflow = float(d["inflow"])
        outflow = float(d["outflow"])

        # чистый приток
        net = inflow - outflow

        return round(net, 2)

    except Exception as e:
        print("API error:", e)
        return 0