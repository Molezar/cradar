import os
import requests

COINGLASS_URL = "https://open-api.coinglass.com/public/v2/indicator/exchange_netflow"

COINGLASS_API_KEY = os.getenv("COINGLASS_API_KEY")

if not COINGLASS_API_KEY:
    raise Exception("COINGLASS_API_KEY is not set")

HEADERS = {
    "coinglassSecret": COINGLASS_API_KEY,
    "Accept": "application/json"
}

def btc_inflow_last_minutes(minutes=60):
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

    r = requests.get(COINGLASS_URL, params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()["data"][0]

    inflow = float(data["inflow"])
    outflow = float(data["outflow"])

    return round(inflow - outflow, 2)