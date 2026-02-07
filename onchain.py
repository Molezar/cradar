import requests
import time

# -----------------------
# Настройки Binance адресов
# -----------------------
BINANCE_ADDRESSES = [
    "bc1q2s6gk6v5f3z7m0t3r9d5l2n7j8k9y0q4v5w6e7",  # пример живого депозита
    "bc1q3z9f8e6v7m4p1n2r5d8k6t0y3l2w1v5e4q9j7",
    "bc1q4f7g8h5j2k0m9n1r6t3w7y8v5e2q4l0p3d6c8"
]

# -----------------------
# Bitquery API
# -----------------------
BITQUERY_URL = "https://graphql.bitquery.io"
BITQUERY_API_KEY = "YOUR_API_KEY_HERE"  # вставь токен Bitquery

def btc_inflow_last_minutes(minutes=360, test_mode=False):
    """
    minutes = за сколько минут считаем (360 = 6 часов)
    test_mode = True -> возвращает случайные данные
    test_mode = False -> реальные on-chain inflow через Bitquery
    """
    if test_mode:
        import random
        return round(random.uniform(100, 1500), 2)

    # Определяем период
    from datetime import datetime, timedelta
    till = datetime.utcnow()
    since = till - timedelta(minutes=minutes)
    till_str = till.strftime("%Y-%m-%dT%H:%M:%S")
    since_str = since.strftime("%Y-%m-%dT%H:%M:%S")

    total_btc = 0

    for addr in BINANCE_ADDRESSES:
        query = """
        query ($addr: String!, $since: ISO8601DateTime!, $till: ISO8601DateTime!) {
          bitcoin(network: bitcoin) {
            outputs(
              outputAddress: {is: $addr}
              date: {since: $since, till: $till}
              options: {limit: 1000}
            ) {
              value
            }
          }
        }
        """

        variables = {
            "addr": addr,
            "since": since_str,
            "till": till_str
        }

        try:
            resp = requests.post(
                BITQUERY_URL,
                json={"query": query, "variables": variables},
                headers={"X-API-KEY": BITQUERY_API_KEY},
                timeout=20
            )
            resp.raise_for_status()
            data = resp.json()
            outputs = data["data"]["bitcoin"]["outputs"]
            for o in outputs:
                total_btc += o.get("value", 0)
        except Exception as e:
            print(f"Error fetching {addr}: {e}")
            continue

    return round(total_btc, 8)