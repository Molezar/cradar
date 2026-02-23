import time
from collections import defaultdict

from database.database import get_db
from logger import get_logger

logger = get_logger(__name__)

SWEEP_THRESHOLD = 3


def get_exchange_clusters(cursor):
    return cursor.execute("""
        SELECT id, name
        FROM clusters
        WHERE cluster_type='EXCHANGE'
    """).fetchall()


def get_recent_whale_txs(cursor, since_ts):
    return cursor.execute("""
        SELECT txid
        FROM whale_classification
        WHERE time > ?
    """, (since_ts,)).fetchall()


def expand_exchange_cluster_from_db(cursor, cluster_id, name):

    logger.info(f"[CLUSTER] Expanding {name} from DB")

    now = int(time.time())
    since = now - (30 * 24 * 3600)

    txs = get_recent_whale_txs(cursor, since)

    candidates = defaultdict(int)

    for row in txs:
        txid = row["txid"]

        rows = cursor.execute("""
            SELECT address
            FROM tx_outputs
            WHERE txid=?
        """, (txid,)).fetchall()

        for r in rows:
            candidates[r["address"]] += 1

    learned = 0

    for addr, count in candidates.items():

        if count < SWEEP_THRESHOLD:
            continue

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
            """, (addr, cluster_id, 0.6, now, now))

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

        try:
            expand_exchange_cluster_from_db(c, cluster_id, name)
        except Exception as e:
            logger.exception(f"[CLUSTER] Expansion error: {e}")

    db.commit()
    db.close()


if __name__ == "__main__":
    while True:
        run_cluster_expansion()
        time.sleep(60 * 30)