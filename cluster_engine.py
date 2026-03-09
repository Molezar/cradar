# cluster_engine.py
import time
from collections import defaultdict

from database.database import get_db
from logger import get_logger

logger = get_logger(__name__)

SWEEP_THRESHOLD = 5
LOOKBACK_DAYS = 30


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


def detect_change_addresses(cursor, txids, cluster_id, now):
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

    learned = 0

    for txid, outputs in tx_outputs.items():

        # change обычно когда ровно 2 выхода
        if len(outputs) != 2:
            continue

        addr1, val1 = outputs[0]
        addr2, val2 = outputs[1]

        # выбираем больший выход как change
        if val1 > val2:
            change_addr = addr1
        else:
            change_addr = addr2

        # фильтр modern change address
        if not change_addr or not change_addr.startswith("bc1"):
            continue

        # проверяем что адрес ещё не кластеризован
        existing = cursor.execute("""
            SELECT cluster_id
            FROM cluster_addresses
            WHERE address=?
        """, (change_addr,)).fetchone()

        if existing:
            continue

        cursor.execute("""
            INSERT INTO cluster_addresses
            (address, cluster_id, confidence, first_seen, last_seen)
            VALUES (?,?,?,?,?)
        """, (change_addr, cluster_id, 0.7, now, now))

        learned += 1

    return learned


def detect_multi_input_exchange(cursor, txids, cluster_id, now):

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

    for txid, addresses in tx_inputs.items():

        # multi-input только если больше одного input
        if len(addresses) < 2:
            continue

        exchange_seen = False

        # проверяем есть ли exchange input
        for addr in addresses:
            r = cursor.execute("""
                SELECT cluster_id
                FROM cluster_addresses
                WHERE address=?
            """, (addr,)).fetchone()

            if r and r["cluster_id"] == cluster_id:
                exchange_seen = True
                break

        if not exchange_seen:
            continue

        # расширяем cluster
        for addr in addresses:

            existing = cursor.execute("""
                SELECT cluster_id
                FROM cluster_addresses
                WHERE address=?
            """, (addr,)).fetchone()

            # если адрес уже в другом кластере — пропускаем
            if existing and existing["cluster_id"] != cluster_id:
                continue

            if existing:
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
                """, (addr, cluster_id, 0.8, now, now))

                learned += 1

    return learned   


def expand_exchange_cluster_from_db(cursor, cluster_id, name):
    logger.info(f"[CLUSTER] Expanding {name} from DB")

    now = int(time.time())
    since = now - (LOOKBACK_DAYS * 24 * 3600)

    txids = get_recent_exchange_txs(cursor, since, cluster_id)

    if not txids:
        return

    # change detection
    change_learned = detect_change_addresses(cursor, txids, cluster_id, now)
    if change_learned:
        logger.info(f"[CLUSTER] {name} learned {change_learned} change addresses")
    # multi-input detection
    multi_learned = detect_multi_input_exchange(cursor, txids, cluster_id, now)
    
    if multi_learned:
        logger.info(f"[CLUSTER] {name} learned {multi_learned} multi-input addresses")

    # 1️⃣ Собираем адреса всех tx_outputs сразу
    placeholders = ",".join("?" * len(txids))
    rows = cursor.execute(f"""
        SELECT address
        FROM tx_outputs
        WHERE txid IN ({placeholders})
    """, txids).fetchall()

    candidates = defaultdict(int)
    for r in rows:
        candidates[r["address"]] += 1

    learned = 0
    for addr, count in candidates.items():
        if count < SWEEP_THRESHOLD:
            continue

        # пропускаем если адрес уже в другом кластере
        existing = cursor.execute("""
            SELECT cluster_id, confidence
            FROM cluster_addresses
            WHERE address=?
        """, (addr,)).fetchone()
        
        if existing and existing["cluster_id"] != cluster_id:
            continue

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
        
        # 🔹 логируем новый размер кластера
        new_size = cursor.execute("""
            SELECT size FROM clusters WHERE id=?
        """, (cluster_id,)).fetchone()["size"]
    
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