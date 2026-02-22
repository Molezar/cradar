import time
import requests
from collections import defaultdict

from database.database import get_db
from logger import get_logger

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = get_logger(__name__)

MEMPOOL_ADDR = "https://mempool.space/api/address/"
CLUSTER_WINDOW = 30 * 24 * 3600
SWEEP_THRESHOLD = 3

# -------- safe session ----------

session = requests.Session()
retries = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
)
session.mount("https://", HTTPAdapter(max_retries=retries))


def fetch_txs(address):
    try:
        r = session.get(MEMPOOL_ADDR + address + "/txs", timeout=20)

        if r.status_code == 429:
            logger.warning("[CLUSTER] 429 rate limit")
            return []

        if r.status_code != 200:
            return []

        return r.json()

    except Exception as e:
        logger.warning(f"[CLUSTER] fetch_txs error: {e}")
        return []


def get_exchange_clusters(cursor):
    return cursor.execute("""
        SELECT id, name
        FROM clusters
        WHERE cluster_type='EXCHANGE'
    """).fetchall()


def expand_exchange_cluster(cursor, cluster_id, cold_address, name):

    logger.info(f"[CLUSTER] Expanding {name}")

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

        for vout in tx.get("vout", []):
            addr = vout.get("scriptpubkey_address")
            if addr and addr != cold_address:
                candidates[addr] += 1

    learned = 0

    for addr, count in candidates.items():

        if count < SWEEP_THRESHOLD:
            continue

        score = min(1.0, count / 10)

        existing = cursor.execute("""
            SELECT cluster_id, confidence
            FROM cluster_addresses
            WHERE address=?
        """, (addr,)).fetchone()

        if existing:

            if existing["cluster_id"] == cluster_id:

                cursor.execute("""
                    UPDATE cluster_addresses
                    SET confidence = MIN(1.0, confidence + 0.05),
                        last_seen = ?
                    WHERE address=?
                """, (now, addr))

        else:
            cursor.execute("""
                INSERT INTO cluster_addresses
                (address, cluster_id, confidence, first_seen, last_seen)
                VALUES (?,?,?,?,?)
            """, (addr, cluster_id, score, now, now))

            learned += 1

    if learned > 0:
        cursor.execute("""
            UPDATE clusters
            SET size = (
                SELECT COUNT(*) FROM cluster_addresses WHERE cluster_id=?
            ),
                last_updated=?
            WHERE id=?
        """, (cluster_id, now, cluster_id))


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
            WHERE cluster_id=? AND confidence >= 0.95
        """, (cluster_id,)).fetchall()

        for a in anchors:
            try:
                expand_exchange_cluster(
                    c,
                    cluster_id,
                    a["address"],
                    name
                )
            except Exception as e:
                logger.exception(f"[CLUSTER] Expansion error: {e}")

    db.commit()
    db.close()


if __name__ == "__main__":
    while True:
        run_cluster_expansion()
        time.sleep(60 * 30)