# cluster_scanner.py
import time
import requests

from database.database import get_db
from logger import get_logger

logger = get_logger(__name__)

MEMPOOL_API = "https://mempool.space/api/address"
SCAN_LIMIT = 25


def scan_exchange_anchors():
    logger.info("[ANCHOR_SCAN] Starting cold wallet scan")

    conn = get_db()
    c = conn.cursor()

    rows = c.execute("""
        SELECT address, cluster_id
        FROM cluster_addresses
        WHERE confidence = 1.0
    """).fetchall()

    total_rows = len(rows)
    logger.info(f"[ANCHOR_SCAN] Total addresses to scan: {total_rows}")

    learned = 0

    for idx, r in enumerate(rows, 1):
        addr = r["address"]
        cluster_id = r["cluster_id"]
        logger.info(f"[ANCHOR_SCAN] Scanning {idx}/{total_rows}: {addr} (cluster {cluster_id})")

        try:
            url = f"{MEMPOOL_API}/{addr}/txs"
            resp = requests.get(url, timeout=10)

            if resp.status_code != 200:
                logger.warning(f"[ANCHOR_SCAN] {addr} returned status {resp.status_code}")
                continue

            txs = resp.json()[:SCAN_LIMIT]

            for tx in txs:
                for vin in tx.get("vin", []):
                    prev = vin.get("prevout", {})
                    a = prev.get("scriptpubkey_address")

                    if not a:
                        continue

                    existing = c.execute("""
                        SELECT cluster_id
                        FROM cluster_addresses
                        WHERE address=?
                    """, (a,)).fetchone()

                    if existing:
                        continue

                    c.execute("""
                        INSERT INTO cluster_addresses
                        (address, cluster_id, confidence, first_seen, last_seen)
                        VALUES (?, ?, 0.75, ?, ?)
                    """, (a, cluster_id, int(time.time()), int(time.time())))

                    learned += 1
                    logger.info(f"[ANCHOR_SCAN] Learned new address {a} for cluster {cluster_id}")

            if idx % 10 == 0 or idx == total_rows:
                logger.info(f"[ANCHOR_SCAN] Progress: {idx}/{total_rows} addresses scanned, learned so far: {learned}")

        except Exception as e:
            logger.warning(f"[ANCHOR_SCAN] Failed for {addr}: {e}")

    conn.commit()
    conn.close()

    logger.info(f"[ANCHOR_SCAN] Scan finished, total learned addresses: {learned}")