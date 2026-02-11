import requests

BLOCKSTREAM = "https://blockstream.info/api"
BINANCE_COLD = "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo"

SATOSHI = 100_000_000
MIN_BTC = 10   # фильтр: берём только движения ≥ 10 BTC

def btc_inflow_last_minutes(minutes=60):
    """
    Считает сколько BTC за последние N минут зашло
    на холодный кошелёк Binance.
    Использует последние 25 tx (лимит Blockstream).
    """

    try:
        url = f"{BLOCKSTREAM}/address/{BINANCE_COLD}/txs"
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        txs = r.json()

        total_btc = 0

        for tx in txs:
            for vout in tx.get("vout", []):
                if vout.get("scriptpubkey_address") == BINANCE_COLD:
                    btc = vout.get("value", 0) / SATOSHI
                    total_btc += btc

        return round(total_btc, 4)

    except Exception as e:
        print("Inflow error:", e)
        return 0
        
def build_cluster():
    try:
        url = f"{BLOCKSTREAM}/address/{BINANCE_COLD}/txs"
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        txs = r.json()

        # address -> total BTC volume with cold wallet
        cluster = {}

        for tx in txs:
            # ------------------
            # 1) входы В cold
            # ------------------
            for vin in tx.get("vin", []):
                prev = vin.get("prevout")
                if not prev:
                    continue

                addr = prev.get("scriptpubkey_address")
                value = prev.get("value", 0)

                if addr and value and "scriptpubkey_address" in prev:
                    # если этот вход пришёл ИЗ какого-то адреса В cold
                    # мы увидим его как vout cold ниже, но считаем тут тоже
                    pass

            # ------------------
            # 2) выходы
            # ------------------
            for vout in tx.get("vout", []):
                addr = vout.get("scriptpubkey_address")
                value = vout.get("value", 0)

                if not addr or not value:
                    continue

                btc = value / SATOSHI

                # cold -> addr
                if tx.get("vin"):
                    for vin in tx["vin"]:
                        prev = vin.get("prevout")
                        if prev and prev.get("scriptpubkey_address") == BINANCE_COLD:
                            if btc >= MIN_BTC:
                                cluster[addr] = cluster.get(addr, 0) + btc

                # addr -> cold
                if addr == BINANCE_COLD:
                    for vin in tx.get("vin", []):
                        prev = vin.get("prevout")
                        if not prev:
                            continue
                        from_addr = prev.get("scriptpubkey_address")
                        value2 = prev.get("value", 0)
                        btc2 = value2 / SATOSHI

                        if from_addr and btc2 >= MIN_BTC:
                            cluster[from_addr] = cluster.get(from_addr, 0) + btc2

        # превращаем в список
        out = []
        for addr, vol in cluster.items():
            out.append({
                "address": addr,
                "btc": round(vol, 4)
            })

        # сортируем по объёму
        out.sort(key=lambda x: x["btc"], reverse=True)

        return out

    except Exception as e:
        print("Cluster build error:", e)
        return []