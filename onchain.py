import requests

BINANCE_COLD = "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo"

def get_txs(address):
    url = f"https://blockstream.info/api/address/{address}/txs"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()

def extract_neighbors(address, txs):
    neigh = set()

    for tx in txs:
        for vin in tx.get("vin", []):
            prev = vin.get("prevout")
            if prev:
                a = prev.get("scriptpubkey_address")
                if a and a != address:
                    neigh.add(a)

        for vout in tx.get("vout", []):
            a = vout.get("scriptpubkey_address")
            if a and a != address:
                neigh.add(a)

    return neigh

def build_cluster():
    txs = get_txs(BINANCE_COLD)[:30]

    neighbors = extract_neighbors(BINANCE_COLD, txs)

    nodes = [{"id": BINANCE_COLD, "group": 0}]
    links = []

    for a in neighbors:
        nodes.append({"id": a, "group": 1})
        links.append({"source": BINANCE_COLD, "target": a})

    return {"nodes": nodes, "links": links}