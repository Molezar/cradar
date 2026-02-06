import random
import time
# import requests   # <- закомментировали, чтобы не дергать блокчейн пока

# Binance hot wallet (основной приёмник)
BINANCE_ADDRESSES = {
    "3JZq4atUahhuA9rLhXLMhhTo133J9rF97j",   # Binance
}

BLOCKSTREAM = "https://blockstream.info/api"

# ---------------------------------------------
# ОРИГИНАЛЬНЫЙ ОНЧЕЙН-КОД (СОХРАНЁН, НО ОТКЛЮЧЕН)
# ---------------------------------------------
"""
def get_recent_blocks(limit=6):
    r = requests.get(f"{BLOCKSTREAM}/blocks")
    return r.json()[:limit]

def get_block_txs(block_hash):
    r = requests.get(f"{BLOCKSTREAM}/block/{block_hash}/txs")
    return r.json()

def btc_inflow_last_minutes(minutes=60):
    now = int(time.time())
    cutoff = now - minutes * 60
    total_sats = 0

    blocks = get_recent_blocks(8)

    for b in blocks:
        txs = get_block_txs(b["id"])

        for tx in txs:
            if tx["status"]["block_time"] < cutoff:
                continue

            for vout in tx["vout"]:
                addr = vout.get("scriptpubkey_address")
                if addr in BINANCE_ADDRESSES:
                    total_sats += vout["value"]

    return round(total_sats / 100_000_000, 2)
"""
# ---------------------------------------------

# ВРЕМЕННАЯ ЗАГЛУШКА (для отладки MiniApp)
def btc_inflow_last_minutes(minutes=60):
    return round(random.uniform(100, 500), 2)