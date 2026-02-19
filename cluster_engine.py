import time
import requests
from collections import defaultdict
from database.database import get_db
from logger import get_logger

logger = get_logger(__name__)

MEMPOOL_ADDR = "https://mempool.space/api/address/"
CLUSTER_WINDOW = 30 * 24 * 3600
SWEEP_THRESHOLD = 3


# =====================================================
# Utils
# =====================================================

def fetch_txs(address):
    try:
        r = requests.get(MEMPOOL_ADDR + address + "/txs", timeout=15)
        if r.status_code != 200:
            return []
        return r.json()
    except:
        return []


def get_exchange_clusters(cursor):
    return cursor.execute("""
        SELECT id, name
        FROM clusters
        WHERE cluster_type='EXCHANGE'
    """).fetchall()


# =====================================================
# Exchange cluster expansion (offline)
# =====================================================

def expand_exchange_cluster(cluster_id, cold_address, name):
    logger.info(f"[CLUSTER] Expanding {name} via {cold_address[:10]}")

    txs = fetch_txs(cold_address)
    now = int(time.time())

    candidates = defaultdict(int)

    for tx in txs:
        block_time = tx.get("status", {}).get("block_time", now)
        if abs(now - block_time) > CLUSTER_WINDOW:
            continue

        for vin in tx.get("vin", []):
            prev = vin.get("prevout", {})
            addr = prev.get("scriptpubkey_address")
            if addr and addr != cold_address:
                candidates[addr] += 1

    db = get_db()
    c = db.cursor()

    for addr, count in candidates.items():
        if count < SWEEP_THRESHOLD:
            continue

        score = min(1.0, count / 10)

        existing = c.execute("""
            SELECT cluster_id, confidence
            FROM cluster_addresses
            WHERE address=?
        """, (addr,)).fetchone()

        if existing:
            if existing["cluster_id"] == cluster_id:
                c.execute("""
                    UPDATE cluster_addresses
                    SET confidence = MIN(1.0, confidence + 0.1),
                        last_seen = ?
                    WHERE address=?
                """, (now, addr))
        else:
            logger.info(f"[CLUSTER] Learned {addr[:10]} as {name} score={score:.2f}")
            c.execute("""
                INSERT INTO cluster_addresses
                (address, cluster_id, confidence, first_seen, last_seen)
                VALUES (?,?,?,?,?)
            """, (addr, cluster_id, score, now, now))

    db.commit()
    db.close()


# =====================================================
# Entry
# =====================================================

def run_cluster_expansion():
    db = get_db()
    c = db.cursor()

    exchange_clusters = get_exchange_clusters(c)

    for row in exchange_clusters:
        cluster_id = row["id"]
        name = row["name"]

        anchors = c.execute("""
            SELECT address
            FROM cluster_addresses
            WHERE cluster_id=? AND confidence=1.0
        """, (cluster_id,)).fetchall()

        for a in anchors:
            try:
                expand_exchange_cluster(cluster_id, a["address"], name)
            except Exception as e:
                logger.exception(f"[CLUSTER] Expansion error: {e}")

    db.close()


if __name__ == "__main__":
    while True:
        run_cluster_expansion()
        time.sleep(60 * 30)