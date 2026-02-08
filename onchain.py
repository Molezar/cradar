import os
import requests

COINGLASS_URL = "https://open-api.coinglass.com/public/v2/indicator/exchange_netflow"
COINGLASS_API_KEY = os.getenv("COINGLASS_API_KEY")

HEADERS = {
    "coinglassSecret": COINGLASS_API_KEY or "",
    "Accept": "application/json"
}

def btc_inflow_last_minutes(minutes=60):
    try:
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

        r = requests.get(
            COINGLASS_URL,
            params=params,
            headers=HEADERS,
            timeout=20
        )

        print("Coinglass status:", r.status_code)
        print("Coinglass text:", r.text[:300])

        if r.status_code != 200:
            return 0

        j = r.json()

        if "data" not in j or not j["data"]:
            return 0

        row = j["data"][0]

        inflow = float(row.get("inflow", 0))
        outflow = float(row.get("outflow", 0))

        return round(inflow - outflow, 2)

    except Exception as e:
        print("API crash:", e)
        return 0