import time
import requests

# Реальные Binance hot wallets (несколько, чтобы inflow точно был)
BINANCE_ADDRESSES = [
    "3JZq4atUahhuA9rLhXLMhhTo133J9rF97j",   # Binance 1
    "3FZbgi29cpjq2GjdwV8eyHuJJnkLtktZc5",   # Binance 2
    "3D2oetdNuZUqQHPJmcMDDHYoqkyNVsFk9r",   # Binance 3
    "bc1q0c9l8z6gk4y6m9r6z4yqj3v7p6s9xw2m4v9a7d"  # Binance Bech32
]

BLOCKSTREAM = "https://blockstream.info/api"


def get_address_txs(addr):
    url = f"{BLOCKSTREAM}/address/{addr}/txs"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()


def btc_inflow_last_minutes(minutes=360):   # 360 = последние 6 часов
    cutoff = int(time.time()) - minutes * 60
    total_sats = 0

    for addr in BINANCE_ADDRESSES:
        try:
            txs = get_address_txs(addr)
        except Exception:
            continue

        for tx in txs:
            status = tx.get("status", {})
            block_time = status.get("block_time")

            if not block_time or block_time < cutoff:
                continue

            # считаем только ВХОД в Binance
            for vout in tx["vout"]:
                if vout.get("scriptpubkey_address") == addr:
                    total_sats += vout["value"]

    return round(total_sats / 100_000_000, 2)