# cluster_engine.py
import time
from collections import defaultdict

from database.database import get_db
from logger import get_logger

logger = get_logger(__name__)

SWEEP_THRESHOLD = 5
LOOKBACK_DAYS = 30
FINGERPRINT_THRESHOLD = 5
BATCH_SIZE = 5000
BATCH_SLEEP = 0.02


def get_exchange_clusters(cursor):
    return cursor.execute("""
        SELECT id, name
        FROM clusters
        WHERE cluster_type='EXCHANGE'
    """).fetchall()


def get_recent_exchange_txs(cursor, since_ts, cluster_id):
    rows = cursor.execute("""
        SELECT txid
        FROM whale_classification
        WHERE time > ?
        AND (from_cluster = ? OR to_cluster = ?)
    """, (since_ts, cluster_id, cluster_id)).fetchall()
    return [r["txid"] for r in rows]


def try_fingerprint(cursor, addr):
    prefix = addr[:6]
    length = len(addr)
    fp = cursor.execute("""
        SELECT cluster_id, count
        FROM address_fingerprint
        WHERE prefix=? AND length=?
        ORDER BY count DESC
        LIMIT 1
    """, (prefix, length)).fetchone()
    if fp and fp["count"] >= FINGERPRINT_THRESHOLD:
        return fp["cluster_id"]
    return None


def update_fingerprint(cursor, addr, cluster_id):
    prefix = addr[:6]
    length = len(addr)
    cursor.execute("""
        INSERT INTO address_fingerprint
        (prefix,length,cluster_id,count)
        VALUES (?,?,?,1)
        ON CONFLICT(prefix,length,cluster_id)
        DO UPDATE SET count = count + 1
    """, (prefix, length, cluster_id))


def insert_or_update_address(cursor, cache, addr, cluster_id, confidence, now):
    existing = cache.get(addr)
    if existing is None:
        existing = cursor.execute("""
            SELECT cluster_id, confidence
            FROM cluster_addresses
            WHERE address=?
        """, (addr,)).fetchone()
        if existing:
            existing = dict(existing)
                existing["confidence"] = existing.get("confidence", confidence)
        cache[addr] = existing

    if existing:
        if existing["cluster_id"] != cluster_id:
            return False
        new_conf = min(1.0, existing["confidence"] + 0.05)
        cursor.execute("""
            UPDATE cluster_addresses
            SET confidence = ?, last_seen = ?
            WHERE address=?
        """, (new_conf, now, addr))
        cache[addr]["confidence"] = new_conf
    else:
        fp_cluster = try_fingerprint(cursor, addr)
        if fp_cluster and fp_cluster != cluster_id:
            return False
        cursor.execute("""
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
        # sleep только если текущая пачка полная
        if len(batch) == BATCH_SIZE:
            time.sleep(BATCH_SLEEP)
    return learned


def detect_change_addresses(cursor, txids, cluster_id, now, cache):
    if not txids:
        return 0

    placeholders = ",".join("?" * len(txids))
    rows = cursor.execute(f"""
        SELECT o.txid, o.address, o.btc
        FROM tx_outputs o
        WHERE o.txid IN ({placeholders})
    """, txids).fetchall()

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

    placeholders = ",".join("?" * len(txids))
    rows = cursor.execute(f"""
        SELECT txid, address
        FROM tx_inputs
        WHERE txid IN ({placeholders})
    """, txids).fetchall()

    tx_inputs = defaultdict(list)
    for r in rows:
        tx_inputs[r["txid"]].append(r["address"])

    learned = 0
    for addresses in tx_inputs.values():
        if len(addresses) < 2:
            continue
        # хотя бы один адрес уже в кластере
        has_in_cluster = False
        for a in addresses:
            cached_cluster = cache.get(a, {"cluster_id": None})["cluster_id"]
            if cached_cluster == cluster_id:
                has_in_cluster = True
                break
            row = cursor.execute("SELECT cluster_id FROM cluster_addresses WHERE address=?", (a,)).fetchone()
            if row and row["cluster_id"] == cluster_id:
                has_in_cluster = True
                break
        if not has_in_cluster:
            continue
        learned += batch_process_addresses(addresses, cursor, cache, cluster_id, 0.8, now)
    return learned


def expand_exchange_cluster_from_db(cursor, cluster_id, name):
    logger.info(f"[CLUSTER] Expanding {name} from DB")

    now = int(time.time())
    since = now - (LOOKBACK_DAYS * 24 * 3600)

    cache = {}
    txids = get_recent_exchange_txs(cursor, since, cluster_id)
    if not txids:
        return

    change_learned = detect_change_addresses(cursor, txids, cluster_id, now, cache)
    if change_learned:
        logger.info(f"[CLUSTER] {name} learned {change_learned} change addresses")

    multi_learned = detect_multi_input_exchange(cursor, txids, cluster_id, now, cache)
    if multi_learned:
        logger.info(f"[CLUSTER] {name} learned {multi_learned} multi-input addresses")

    placeholders = ",".join("?" * len(txids))
    rows = cursor.execute(f"""
        SELECT address
        FROM tx_outputs
        WHERE txid IN ({placeholders})
    """, txids).fetchall()

    candidates = defaultdict(int)
    for r in rows:
        candidates[r["address"]] += 1

    addresses = [addr for addr, count in candidates.items() if count >= SWEEP_THRESHOLD]
    learned = batch_process_addresses(addresses, cursor, cache, cluster_id, 0.6, now)

    if learned > 0:
        cursor.execute("""
            UPDATE clusters
            SET size = (SELECT COUNT(*) FROM cluster_addresses WHERE cluster_id=?),
                last_updated=?
            WHERE id=?
        """, (cluster_id, now, cluster_id))
        new_size = cursor.execute("SELECT size FROM clusters WHERE id=?", (cluster_id,)).fetchone()["size"]
        logger.info(f"[CLUSTER] {name} size now {new_size}")


def run_cluster_expansion():
    db = None
    try:
        db = get_db()
        c = db.cursor()
        clusters = get_exchange_clusters(c)
        for row in clusters:
            cluster_id = row["id"]
            name = row["name"]
            try:
                expand_exchange_cluster_from_db(c, cluster_id, name)
            except Exception as e:
                logger.exception(f"[CLUSTER] Expansion error for {name}: {e}")
        db.commit()
    except Exception:
        logger.exception("[CLUSTER] Run expansion failed")
    finally:
        if db:
            db.close()


if __name__ == "__main__":
    while True:
        run_cluster_expansion()
        time.sleep(60 * 30)