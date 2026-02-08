import os
import requests

COINGLASS_KEY = os.getenv("COINGLASS_KEY")
BASE_URL = "https://open-api.coinglass.com/public/v2/indicator"

def get_coinglass_data(symbol="BTC", exchange="Binance", interval="1h"):
    """
    Возвращает словарь с данными по BTC на Binance:
    - totalOpenInterest
    - longOpenInterest
    - shortOpenInterest
    - fundingRate
    """
    headers = {"coinglassSecret": COINGLASS_KEY}
    
    # Open Interest
    try:
        r = requests.get(
            f"{BASE_URL}/open_interest",
            params={"symbol": symbol, "exchange": exchange, "interval": interval},
            headers=headers,
            timeout=10
        )
        r.raise_for_status()
        oi_data = r.json().get("data", {})
    except Exception:
        oi_data = {}

    # Funding Rate
    try:
        r = requests.get(
            f"{BASE_URL}/funding_rate",
            params={"symbol": symbol, "exchange": exchange},
            headers=headers,
            timeout=10
        )
        r.raise_for_status()
        funding_data = r.json().get("data", {})
    except Exception:
        funding_data = {}

    return {
        "oi_total": oi_data.get("totalOpenInterest", 0),
        "oi_long": oi_data.get("longOpenInterest", 0),
        "oi_short": oi_data.get("shortOpenInterest", 0),
        "funding_rate": funding_data.get("fundingRate", 0)
    }