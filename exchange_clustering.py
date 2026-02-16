import time
import requests
from collections import defaultdict
from database.database import get_db
from logger import get_logger

logger = get_logger(__name__)

MEMPOOL_ADDR = "https://mempool.space/api/address/"
MIN_SCORE = 0.6
SWEEP_THRESHOLD = 3        # how many times an address must sweep to cold wallet
CLUSTER_WINDOW = 30 * 24 * 3600  # 30 days


# ============================
# API
# ============================

def fetch_txs(address):
    url = MEMPOOL_ADDR + address + "/txs"
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return []
    return r.json()


# ============================
# Core clustering logic
# ============================

def discover_cluster(exchange, cold_address):
    logger.info(f"[CLUSTER] Scanning cold wallet {exchange} {cold_address[:10]}")

    txs = fetch_txs(cold_address)
    now = int(time.time())

    candidates = defaultdict(int)

    for tx in txs:
        if abs(now - tx.get("status", {}).get("block_time", now)) > CLUSTER_WINDOW:
            continue

        for vin in tx.get("vin", []):
            prev = vin.get("prevout", {})
            addr = prev.get("scriptpubkey_address")

            if not addr:
                continue

            # exclude self
            if addr == cold_address:
                continue

            candidates[addr] += 1

    # Now evaluate candidates
    db = get_db()
    c = db.cursor()

    for addr, count in candidates.items():
        if count < SWEEP_THRESHOLD:
            continue

        score = min(1.0, count / 10)

        existing = c.execute(
            "SELECT exchange, score FROM exchange_addresses WHERE address=?",
            (addr,)
        ).fetchone()

        if existing:
            if score > existing["score"]:
                c.execute(
                    "UPDATE exchange_addresses SET score=? WHERE address=?",
                    (score, addr)
                )
        else:
            logger.info(f"[CLUSTER] Learned {addr[:10]} as {exchange} score={score:.2f}")
            c.execute("""
                INSERT INTO exchange_addresses(address,exchange,is_anchor,score)
                VALUES(?,?,0,?)
            """, (addr, exchange, score))

    db.commit()
    db.close()


# ============================
# Entry point
# ============================

def run_clustering():
    db = get_db()
    c = db.cursor()

    anchors = c.execute("""
        SELECT address, exchange
        FROM exchange_addresses
        WHERE is_anchor = 1
    """).fetchall()

    db.close()

    for a in anchors:
        try:
            discover_cluster(a["exchange"], a["address"])
        except Exception as e:
            logger.exception(f"[CLUSTER] Error on {a['address'][:10]}: {e}")


if __name__ == "__main__":
    while True:
        run_clustering()
        time.sleep(60 * 30)   # every 30 minutes