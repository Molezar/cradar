import time
import requests
import random

# Реальные Binance hot wallets
BINANCE_ADDRESSES = [
    "3JZq4atUahhuA9rLhXLMhhTo133J9rF97j",   # Binance 1
]

BLOCKSTREAM = "https://blockstream.info/api"

# Получаем транзакции для одного адреса
def get_address_txs(addr):
    url = f"{BLOCKSTREAM}/address/{addr}/txs"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()

def btc_inflow_last_minutes(minutes=None, test_mode=False):
    """
    Если test_mode=True, возвращает случайное значение для проверки MiniApp
    Если minutes=None, считает все транзакции без ограничения времени
    """
    if test_mode:
        return round(random.uniform(100, 500), 2)

    cutoff = int(time.time()) - minutes * 60 if minutes else 0
    total_sats = 0

    for addr in BINANCE_ADDRESSES:
        txs = get_address_txs(addr)

        for tx in txs:
            status = tx.get("status", {})
            block_time = status.get("block_time")

            # если транзакция не в блоке или слишком старая — пропускаем
            if block_time is None or block_time < cutoff:
                continue

            # считаем только входящие в Binance outputs
            for vout in tx["vout"]:
                if vout.get("scriptpubkey_address") == addr:
                    total_sats += vout["value"]

    return round(total_sats / 100_000_000, 2)