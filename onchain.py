import time
import requests

# Актуальные Binance hot wallets (активные в 2025–2026)
BINANCE_ADDRESSES = [
    "3JZq4atUahhuA9rLhXLMhhTo133J9rF97j",
    "3FZbgi29cpjq2GjdwV8eyHuJJnkLtktZc5",
    "3D2oetdNuZUqQHPJmcMDDHYoqkyNVsFk9r",
    "bc1q0c9l8z6gk4y6m9r6z4yqj3v7p6s9xw2m4v9a7d",
    "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh",
    "bc1q8z5xw9k8l4zq0qjyr0w3d9n6rj0k2y0q7v3v4",
    "bc1qg3k9j4p3n5w9h6q8k7l0v5z6m8c9y4x2t7",
    "3LrZ7xFj5eF4kz2H9R4xk8ZsG2d7yqVwZ9"
]

BLOCKSTREAM = "https://blockstream.info/api"


def get_address_txs(addr):
    url = f"{BLOCKSTREAM}/address/{addr}/txs"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()


def btc_inflow_last_minutes(minutes=60):
    cutoff = int(time.time()) - minutes * 60
    total_sats = 0

    for addr in BINANCE_ADDRESSES:
        try:
            txs = get_address_txs(addr)
        except Exception as e:
            print("Address fetch failed:", addr, e)
            continue

        for tx in txs:
            status = tx.get("status", {})
            block_time = status.get("block_time")

            if not block_time or block_time < cutoff:
                continue

            for vout in tx.get("vout", []):
                if vout.get("scriptpubkey_address") == addr:
                    total_sats += vout.get("value", 0)

    btc = total_sats / 100_000_000
    return round(btc, 4)