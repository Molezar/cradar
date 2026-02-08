import requests

BLOCKSTREAM = "https://blockstream.info/api"

BINANCE_COLD = "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo"


def build_cluster():
    try:
        url = f"{BLOCKSTREAM}/address/{BINANCE_COLD}/txs"
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        txs = r.json()

        cluster = set()
        cluster.add(BINANCE_COLD)

        for tx in txs:
            # входы
            for vin in tx.get("vin", []):
                prev = vin.get("prevout")
                if prev and "scriptpubkey_address" in prev:
                    cluster.add(prev["scriptpubkey_address"])

            # выходы
            for vout in tx.get("vout", []):
                if "scriptpubkey_address" in vout:
                    cluster.add(vout["scriptpubkey_address"])

        return list(cluster)

    except Exception as e:
        print("Cluster build error:", e)
        return []