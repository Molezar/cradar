# cluster_engine.py
import time
from collections import defaultdict
import sqlite3

from database.database import get_db
from logger import get_logger
from onchain import fetchone_with_retry, fetchall_with_retry, execute_with_retry, executemany_with_retry

logger = get_logger(__name__)

SWEEP_THRESHOLD = 5
LOOKBACK_DAYS = 30
FINGERPRINT_THRESHOLD = 5
BATCH_SIZE = 5000
BATCH_SLEEP = 0.02
SQL_BATCH_SIZE = 900  # 🔥 важно для SQLite


# ✅ универсальный батчевый SELECT с retry
def batched_select(cursor, base_query, items):
    results = []
    for i in range(0, len(items), SQL_BATCH_SIZE):
        batch = items[i:i + SQL_BATCH_SIZE]
        placeholders = ",".join("?" * len(batch))
        query = base_query.format(placeholders=placeholders)
        rows = fetchall_with_retry(cursor, query, batch)
        results.extend(rows)
    return results


def get_exchange_clusters(cursor):
    return fetchall_with_retry(cursor, """
        SELECT id, name
        FROM clusters
        WHERE cluster_type='EXCHANGE'
    """)


def get_recent_exchange_txs(cursor, since_ts, cluster_id):
    rows = fetchall_with_retry(cursor, """
        SELECT txid
        FROM whale_classification
        WHERE time > ?
        AND (from_cluster = ? OR to_cluster = ?)
    """, (since_ts, cluster_id, cluster_id))
    return [r["txid"] for r in rows]


def try_fingerprint(cursor, addr):
    prefix = addr[:6]
    length = len(addr)
    fp = fetchone_with_retry(cursor, """
        SELECT cluster_id, count
        FROM address_fingerprint
        WHERE prefix=? AND length=?
        ORDER BY count DESC
        LIMIT 1
    """, (prefix, length))
    if fp and fp["count"] >= FINGERPRINT_THRESHOLD:
        return fp["cluster_id"]
    return None


def update_fingerprint(cursor, addr, cluster_id):
    prefix = addr[:6]
    length = len(addr)
    execute_with_retry(cursor, """
        INSERT INTO address_fingerprint
        (prefix,length,cluster_id,count)
        VALUES (?,?,?,1)
        ON CONFLICT(prefix,length,cluster_id)
        DO UPDATE SET count = count + 1
    """, (prefix, length, cluster_id))


def insert_or_update_address(cursor, cache, addr, cluster_id, confidence, now):
    existing = cache.get(addr)
    if existing is None:
        row = fetchone_with_retry(cursor, """
            SELECT cluster_id, confidence
            FROM cluster_addresses
            WHERE address=?
        """, (addr,))
        existing = dict(row) if row else None
        cache[addr] = existing

    if existing:
        if existing["cluster_id"] != cluster_id:
            return False
        new_conf = min(1.0, existing["confidence"] + 0.05)
        execute_with_retry(cursor, """
            UPDATE cluster_addresses
            SET confidence = ?, last_seen = ?
            WHERE address=?
        """, (new_conf, now, addr))
        cache[addr]["confidence"] = new_conf
    else:
        fp_cluster = try_fingerprint(cursor, addr)
        if fp_cluster and fp_cluster != cluster_id:
            return False
        execute_with_retry(cursor, """
            INSERT INTO cluster_addresses
            (address, cluster_id, confidence, first_seen, last_seen)
            VALUES (?,?,?,?,?)
        """, (addr, cluster_id, confidence, now, now))
        update_fingerprint(cursor, addr, cluster_id)
        cache[addr] = {"cluster_id": cluster_id, "confidence": confidence}
    return True


def batch_process_addresses(addresses, cursor, cache, cluster_id, confidence, now):
    learned = 0
    for i in range(0, len(addresses), BATCH_SIZE):
        batch = addresses[i:i + BATCH_SIZE]
        for addr in batch:
            if insert_or_update_address(cursor, cache, addr, cluster_id, confidence, now):
                learned += 1
        if len(batch) == BATCH_SIZE:
            time.sleep(BATCH_SLEEP)
    return learned


def detect_change_addresses(cursor, txids, cluster_id, now, cache):
    if not txids:
        return 0

    rows = batched_select(cursor, """
        SELECT o.txid, o.address, o.btc
        FROM tx_outputs o
        WHERE o.txid IN ({placeholders})
    """, txids)

    tx_outputs = defaultdict(list)
    for r in rows:
        tx_outputs[r["txid"]].append((r["address"], r["btc"]))

    addresses = []
    for outputs in tx_outputs.values():
        if len(outputs) < 2:
            continue
        addr1, val1 = outputs[0]
        addr2, val2 = outputs[1]
        if val1 < 0.0001 or val2 < 0.0001:
            continue
        addresses.append(addr1 if val1 > val2 else addr2)

    return batch_process_addresses(addresses, cursor, cache, cluster_id, 0.7, now)


def detect_multi_input_exchange(cursor, txids, cluster_id, now, cache):
    if not txids:
        return 0

    rows = batched_select(cursor, """
        SELECT txid, address
        FROM tx_inputs
        WHERE txid IN ({placeholders})
    """, txids)

    tx_inputs = defaultdict(list)
    for r in rows:
        tx_inputs[r["txid"]].append(r["address"])

    learned = 0
    for addresses in tx_inputs.values():
        if len(addresses) < 2:
            continue

        has_in_cluster = False
        for a in addresses:
            cached = cache.get(a)
            if cached and cached["cluster_id"] == cluster_id:
                has_in_cluster = True
                break

            row = fetchone_with_retry(
                cursor,
                "SELECT cluster_id FROM cluster_addresses WHERE address=?",
                (a,)
            )
            if row and row["cluster_id"] == cluster_id:
                has_in_cluster = True
                break

        if not has_in_cluster:
            continue

        learned += batch_process_addresses(addresses, cursor, cache, cluster_id, 0.8, now)

    return learned


def expand_exchange_cluster_from_db(cursor, cluster_id, name):
    now = int(time.time())
    since = now - (LOOKBACK_DAYS * 24 * 3600)

    cache = {}
    txids = get_recent_exchange_txs(cursor, since, cluster_id)
    if not txids:
        return

    change_learned = detect_change_addresses(cursor, txids, cluster_id, now, cache)
    multi_learned = detect_multi_input_exchange(cursor, txids, cluster_id, now, cache)

    rows = batched_select(cursor, """
        SELECT address
        FROM tx_outputs
        WHERE txid IN ({placeholders})
    """, txids)

    candidates = defaultdict(int)
    for r in rows:
        candidates[r["address"]] += 1

    addresses = [addr for addr, count in candidates.items() if count >= SWEEP_THRESHOLD]
    learned = batch_process_addresses(addresses, cursor, cache, cluster_id, 0.6, now)

    if learned > 0:
        execute_with_retry(cursor, """
            UPDATE clusters
            SET size = (SELECT COUNT(*) FROM cluster_addresses WHERE cluster_id=?),
                last_updated=?
            WHERE id=?
        """, (cluster_id, now, cluster_id))


def run_cluster_expansion():
    db = None
    try:
        db = get_db()
        clusters = get_exchange_clusters(db.cursor())

        for row in clusters:
            cluster_id = row["id"]
            name = row["name"]

            try:
                c = db.cursor()  # ✅ важно
                expand_exchange_cluster_from_db(c, cluster_id, name)
                db.commit()
                time.sleep(0.01)  # (опционально)
            except Exception as e:
                logger.exception(f"[CLUSTER] Expansion error for {name}: {e}")

    except Exception:
        logger.exception("[CLUSTER] Run expansion failed")

    finally:
        if db:
            db.close()


if __name__ == "__main__":
    while True:
        run_cluster_expansion()
        time.sleep(60 * 30)