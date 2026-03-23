# onchain.py
import time
import json
import asyncio
import queue
import sqlite3
from collections import deque, OrderedDict
import websockets

from database.database import get_db
from config import Config
from logger import get_logger

logger = get_logger(__name__)

MIN_TRACK_BTC = Config.MIN_TRACK_BTC
MIN_WHALE_BTC = Config.MIN_WHALE_BTC
ALERT_WHALE_BTC = Config.ALERT_WHALE_BTC
SATOSHI = 100_000_000
MEMPOOL_WS = "wss://mempool.emzy.de/api/v1/ws"

upgrade_queue = set()
_events = queue.Queue()
_seen_txids = set()
_seen_txids_queue = deque()
SEEN_TX_LIMIT = 500000

def get_event_queue():
    return _events


# ==============================================
# Utils
# ==============================================

def _cid(value):
    """Safety extractor for cluster_id (protects from tuple)."""
    if isinstance(value, tuple):
        return value[0]
    return value


# ==============================================
# Cluster resolution
# ==============================================

def resolve_cluster(address, cursor, cache=None):
    if cache is not None and address in cache:
        return cache[address]

    r = fetchone_with_retry(
        cursor,
        """
        SELECT cluster_id, confidence
        FROM cluster_addresses
        WHERE address=?
        """,
        (address,)
    )

    result = (r["cluster_id"], r["confidence"]) if r else (None, 0)

    if cache is not None:
        cache[address] = result

        if len(cache) > 500000:
            cache.clear()

    return result

def update_address_seen(addr, cursor):
    now = int(time.time())

    execute_with_retry(cursor, """
        UPDATE cluster_addresses
        SET last_seen=?
        WHERE address=? AND last_seen < ?
    """, (now, addr, now))

def create_behavioral_cluster(address, cursor, cache=None):
    now = int(time.time())

    existing = fetchone_with_retry(cursor, "SELECT cluster_id FROM cluster_addresses WHERE address=?", (address,))
    if existing:
        return existing["cluster_id"]
    
    # безопасный INSERT в clusters
    execute_with_retry(cursor, """
        INSERT INTO clusters
        (cluster_type, confidence, size, created_at, last_updated)
        VALUES (?, ?, ?, ?, ?)
    """, ("BEHAVIORAL", 0.4, 1, now, now))
    cluster_id = cursor.lastrowid

    # безопасный INSERT в cluster_addresses
    execute_with_retry(cursor, """
        INSERT OR IGNORE INTO cluster_addresses
        (address, cluster_id, confidence, first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?)
    """, (address, cluster_id, 0.4, now, now))

    if cache is not None:
        cache[address] = (cluster_id, 0.4)

    return cluster_id


# ==============================================
# Cluster merge
# ==============================================

def merge_clusters(target_cluster, source_cluster, cursor, cache=None):
    if target_cluster == source_cluster:
        return

    # ===== UPDATE cluster_addresses =====
    execute_with_retry(cursor, """
        UPDATE cluster_addresses
        SET cluster_id=?
        WHERE cluster_id=?
    """, (target_cluster, source_cluster))
        
    # ===== UPDATE whale_classification =====
    execute_with_retry(cursor, """
        UPDATE whale_classification
        SET from_cluster = ?
        WHERE from_cluster = ?
    """, (target_cluster, source_cluster))
    
    execute_with_retry(cursor, """
        UPDATE whale_classification
        SET to_cluster = ?
        WHERE to_cluster = ?
    """, (target_cluster, source_cluster))
    
    # ===== UPDATE exchange_flow =====
    execute_with_retry(cursor, """
        UPDATE exchange_flow
        SET cluster_id = ?
        WHERE cluster_id = ?
    """, (target_cluster, source_cluster))
    
    # ===== UPDATE address_fingerprint =====
    execute_with_retry(cursor, """
        UPDATE address_fingerprint
        SET cluster_id = ?
        WHERE cluster_id = ?
    """, (target_cluster, source_cluster))
    
    # ===== DELETE old cluster =====
    execute_with_retry(cursor, "DELETE FROM clusters WHERE id=?", (source_cluster,))
        
    # ===== UPDATE target cluster size =====
    execute_with_retry(cursor, """
        UPDATE clusters
        SET size = (
            SELECT COUNT(*) FROM cluster_addresses
            WHERE cluster_id=?
        )
        WHERE id=?
    """, (target_cluster, target_cluster))

    # ===== Update cache =====
    if cache is not None:
        for addr, data in list(cache.items()):
            if _cid(data[0]) == source_cluster:
                cache[addr] = (target_cluster, data[1])
                
    # ===== Clear cluster type cache =====
    _cluster_type_cache.pop(source_cluster, None)
    _cluster_type_cache.pop(target_cluster, None)

    # =FIX: remove duplicates after merge =
    execute_with_retry(cursor, """
        DELETE FROM whale_classification
        WHERE rowid NOT IN (
            SELECT MIN(rowid)
            FROM whale_classification
            GROUP BY txid, flow_type, from_cluster, to_cluster
        )
    """)
    logger.info(f"[CLUSTER] merged {source_cluster} → {target_cluster}")
    

# ==============================================
# Parsing
# ==============================================

def get_input_map(tx):
    m = {}
    for vin in tx.get("vin", []):
        prev = vin.get("prevout", {})
        addr = prev.get("scriptpubkey_address")
        val = prev.get("value", 0) / SATOSHI

        if addr and val > 0:
            m[addr] = m.get(addr, 0) + val

    return m

def get_output_map(tx):
    m = {}
    for v in tx.get("vout", []):
        addr = v.get("scriptpubkey_address")
        val = v.get("value", 0) / SATOSHI

        if addr and val > 0:
            m[addr] = m.get(addr, 0) + val

    return m

def store_tx_io(txid, inputs_map, outputs_map, cursor):
    input_rows = [(txid, addr, btc) for addr, btc in inputs_map.items()]
    output_rows = [(txid, addr, btc) for addr, btc in outputs_map.items()]

    executemany_with_retry(cursor, """
        INSERT OR IGNORE INTO tx_inputs (txid, address, btc)
        VALUES (?, ?, ?)
    """, input_rows)

    executemany_with_retry(cursor, """
        INSERT OR IGNORE INTO tx_outputs (txid, address, btc)
        VALUES (?, ?, ?)
    """, output_rows)


# ==============================================
# Behavioral -> Exchange upgrade
# ==============================================

def behavioral_to_exchange(cluster_id, cursor, now):
    lookback = now - (30 * 24 * 3600)

    rows = fetchall_with_retry(
        cursor,
        """
        SELECT txid
        FROM whale_classification
        WHERE time > ? AND (from_cluster=? OR to_cluster=?)
        """,
        (lookback, cluster_id, cluster_id)
    )

    if not rows:
        return False

    txids = [r["txid"] for r in rows]

    multi_input_count = 0
    sweep_count = 0
    fanout_count = 0
    deposit_pattern = 0

    for txid in txids:
        inputs = fetchall_with_retry(
            cursor,
            "SELECT address FROM tx_inputs WHERE txid=?",
            (txid,)
        )
        if len(inputs) > 1:
            multi_input_count += 1

        outputs = fetchall_with_retry(
            cursor,
            "SELECT address FROM tx_outputs WHERE txid=?",
            (txid,)
        )
        if len(outputs) >= 5:
            sweep_count += 1
        if len(outputs) >= 10:
            fanout_count += 1
        if len(inputs) >= 3 and len(outputs) == 1:
            deposit_pattern += 1

    if (
        multi_input_count >= 20
        or sweep_count >= 5
        or fanout_count >= 10
        or deposit_pattern >= 5
    ):
        execute_with_retry(
            cursor,
            """
            UPDATE clusters
            SET cluster_type=?, confidence=?, last_updated=?
            WHERE id=?
            """,
            ("EXCHANGE", 0.9, now, cluster_id)
        )
        logger.info(f"[CLUSTER] Behavioral cluster {cluster_id} upgraded to EXCHANGE")
        return True

    return False


# ==============================================
# Flow classification
# ==============================================
_cluster_type_cache = OrderedDict()
CACHE_LIMIT = 200000

def classify_flow(inputs, outputs, cursor, cache=None):

    in_exchange = {}
    out_exchange = {}
    unknown_inputs = {}
    unknown_outputs = {}

    cluster_cache = cache if cache is not None else {}

    # ===== входящие кластеры =====
    for addr, btc in inputs.items():

        cid, _ = resolve_cluster(addr, cursor, cluster_cache)
        cid = _cid(cid)

        if cid:
            if cid in _cluster_type_cache:
                cluster_type = _cluster_type_cache[cid]
            else:
                row = fetchone_with_retry(
                    cursor,
                    "SELECT cluster_type FROM clusters WHERE id=?",
                    (cid,)
                )
                cluster_type = row["cluster_type"] if row else None
                _cluster_type_cache[cid] = cluster_type
                if len(_cluster_type_cache) > CACHE_LIMIT:
                    _cluster_type_cache.popitem(last=False)
            if cluster_type == "EXCHANGE":
                in_exchange[cid] = in_exchange.get(cid, 0) + btc
        else:
            unknown_inputs[addr] = btc

    # ===== исходящие кластеры =====
    for addr, btc in outputs.items():

        cached = cluster_cache.get(addr)

        if cached:
            cid = _cid(cached[0])
        else:
            cid, _ = resolve_cluster(addr, cursor, cluster_cache)
            cid = _cid(cid)

        if cid:
            if cid in _cluster_type_cache:
                cluster_type = _cluster_type_cache[cid]
            else:
                row = fetchone_with_retry(
                    cursor,
                    "SELECT cluster_type FROM clusters WHERE id=?",
                    (cid,)
                )
                cluster_type = row["cluster_type"] if row else None
                _cluster_type_cache[cid] = cluster_type
                if len(_cluster_type_cache) > CACHE_LIMIT:
                    _cluster_type_cache.popitem(last=False)
    
            if cluster_type == "EXCHANGE":
                out_exchange[cid] = out_exchange.get(cid, 0) + btc
        else:
            unknown_outputs[addr] = btc

    flows = []

    # ======================================
    # INTERNAL exchange flow
    # ======================================
    
    for cid_in, vol in in_exchange.items():
        for cid_out, vol_out in out_exchange.items():
            flows.append((cid_in, cid_out, "INTERNAL", min(vol, vol_out)))
    
    
    # ======================================
    # WITHDRAW (exchange -> unknown)
    # ======================================
    change_addr = detect_change_address(inputs, outputs)

    if change_addr:
        filtered_outputs = {a: b for a, b in outputs.items() if a != change_addr}
    else:
        filtered_outputs = outputs
        
    for cid, vol in in_exchange.items():

        withdraw_vol = min(vol, sum(filtered_outputs.values()))
    
        if unknown_outputs and not out_exchange:
            flows.append((cid, None, "WITHDRAW", withdraw_vol))
    
    
    # ======================================
    # DEPOSIT (unknown -> exchange)
    # ======================================
    
    # [FIX 3] Deposit detection independent
    for cid, vol in out_exchange.items():
        if len(inputs) >= 15 and len(outputs) == 1:
            largest_input = max(inputs.values())
            avg_input = sum(inputs.values()) / len(inputs)
            if largest_input <= avg_input * 5:  # один вход не доминирует
                flows.append((None, cid, "DEPOSIT", vol))

    return flows

def heuristic_flow_classification(inputs, outputs, total_btc):

    flows = []

    num_in = len(inputs)
    num_out = len(outputs)

    largest_output = max(outputs.values()) if outputs else 0
    output_ratio = largest_output / total_btc if total_btc else 0
    flow_btc = sum(outputs.values())
    
    # exchange withdraw pattern
    if num_in <= 2 and num_out >= 2 and output_ratio > 0.8:
        flows.append((None, None, "POSSIBLE_EXCHANGE_WITHDRAW", flow_btc))

    # consolidation
    elif num_in >= 5 and num_out <= 2:
        flows.append((None, None, "CONSOLIDATION", flow_btc))

    # exchange deposit
    elif num_in >= 3 and num_out <= 2:
        flows.append((None, None, "POSSIBLE_EXCHANGE_DEPOSIT", flow_btc))

    elif num_in > 1 and num_out > 1:
        flows.append((None, None, "INTERNAL", flow_btc))

    else:
        flows.append((None, None, "TRANSFER", flow_btc))

    return flows

def is_exchange_withdraw(outputs):

    vals = list(outputs.values())

    if len(vals) < 2:
        return False

    largest = max(vals)
    vals.remove(largest)
    second = max(vals)

    if largest > second * 3:
        return True

    return False

def detect_exchange_consolidation(inputs, outputs):

    if len(inputs) >= 20 and len(outputs) == 1 and sum(inputs.values()) >= 50:
        return True

    total = sum(inputs.values())

    if len(inputs) >= 25 and total >= 50:
        return True

    return False


# ==============================================
# Hot wallet detection
# ==============================================

def detect_hot_wallet(inputs, outputs):

    if len(inputs) != 1:
        return False

    if len(outputs) < 15:
        return False

    total = sum(outputs.values())

    if total < MIN_TRACK_BTC:
        return False

    largest = max(outputs.values())

    if largest > total * 0.5:
        return False

    return True
    

# ==============================================
# Exchange deposit detection
# ==============================================

def detect_exchange_deposit(inputs, outputs):

    # typical exchange deposit pattern:
    # many user inputs -> single exchange address

    if len(outputs) > 3:
        return False

    num_inputs = len(inputs)

    # too few inputs → probably normal transaction
    if num_inputs < 4:
        return False

    total = sum(inputs.values())

    # small totals often consolidation
    if total < MIN_TRACK_BTC:
        return False

    # check distribution (avoid whale consolidation)
    avg_input = total / num_inputs
    largest_input = max(inputs.values())

    # if one input dominates → not deposit
    if largest_input > avg_input * 6:
        return False

    return True


# ==============================================
# Change address detection
# ==============================================

def detect_change_address(inputs, outputs):
    """
    Detect potential change address in a transaction.
    Heuristic: single output that is small and not seen in inputs.
    """
    if not inputs or not outputs:
        return None

    input_addrs = set(inputs.keys())
    output_addrs = set(outputs.keys())

    # candidate outputs not in input addresses
    candidates = output_addrs - input_addrs

    if not candidates:
        return None

    total_out = sum(outputs.values())

    # find smallest candidate
    smallest_addr = min(candidates, key=lambda a: outputs[a])
    smallest_val = outputs[smallest_addr]

    # simple heuristic: if smallest output < 15% of total, consider as change
    if smallest_val < 0.15 * total_out:
        return smallest_addr

    return None


# ==============================================
# Peel chain detection
# ==============================================

def detect_peel_chain(inputs, outputs):

    if len(inputs) != 1 or len(outputs) != 2:
        return None

    total = sum(outputs.values())
    if total == 0:
        return None

    vals = list(outputs.items())
    vals.sort(key=lambda x: x[1], reverse=True)

    large_addr, large_val = vals[0]
    small_addr, small_val = vals[1]
    
    input_addr = list(inputs.keys())[0]
    
    if large_addr == input_addr:
        return None

    ratio = large_val / total

    # typical peel pattern:
    # large output continues chain
    # small output is payout
    if ratio >= 0.7 and small_val >= 0.1:
        return large_addr

    return None
    
    
# =============================================
# TX processing
# =============================================

def fetchone_with_retry(cursor, sql, params=None, retries=5, delay=0.1):
    for _ in range(retries):
        try:
            if params:
                return cursor.execute(sql, params).fetchone()
            return cursor.execute(sql).fetchone()
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                time.sleep(delay)
            else:
                raise
    raise

def fetchall_with_retry(cursor, sql, params=None, retries=5, delay=0.1):
    for _ in range(retries):
        try:
            if params:
                return cursor.execute(sql, params).fetchall()
            return cursor.execute(sql).fetchall()
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                time.sleep(delay)
            else:
                raise
    raise sqlite3.OperationalError(f"Max retries exceeded for SQL fetchall: {sql}")

def execute_with_retry(cursor, sql, params=None, retries=5, delay=0.1):
    """
    Выполняет SQL с retry при sqlite3.OperationalError (database is locked)
    """
    for attempt in range(retries):
        try:
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            return
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                time.sleep(delay)
            else:
                raise
    raise sqlite3.OperationalError(f"Max retries exceeded for SQL: {sql}")

def executemany_with_retry(cursor, sql, seq_of_params, retries=5, delay=0.1):
    for attempt in range(retries):
        try:
            cursor.executemany(sql, seq_of_params)
            return
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                time.sleep(delay)
            else:
                raise
    raise sqlite3.OperationalError(f"Max retries exceeded for SQL executemany: {sql}")
    
def process_tx(tx, cursor, cluster_cache):
    txid = tx.get("txid")

    if not txid or txid in _seen_txids:
        return

    _seen_txids.add(txid)
    _seen_txids_queue.append(txid)
    
    if len(_seen_txids_queue) > SEEN_TX_LIMIT:
        old = _seen_txids_queue.popleft()
        _seen_txids.discard(old)

    inputs = get_input_map(tx)
    outputs = get_output_map(tx)
    if len(outputs) > 200:
        return
    total = sum(outputs.values())

    if total < MIN_TRACK_BTC:
        return

    # ======== Store tx inputs/outputs =========
    input_rows = [(txid, addr, btc) for addr, btc in inputs.items()]
    output_rows = [(txid, addr, btc) for addr, btc in outputs.items()]

    executemany_with_retry(cursor, """
        INSERT OR IGNORE INTO tx_inputs (txid, address, btc)
        VALUES (?, ?, ?)
    """, input_rows)

    executemany_with_retry(cursor, """
        INSERT OR IGNORE INTO tx_outputs (txid, address, btc)
        VALUES (?, ?, ?)
    """, output_rows)

    now = int(time.time())

    # ======================================
    # Exchange consolidation detection
    # ======================================
    if detect_exchange_consolidation(inputs, outputs):
        base_cluster = create_behavioral_cluster(list(inputs.keys())[0], cursor, cluster_cache)
        for addr in inputs.keys():
            execute_with_retry(cursor, """
                INSERT OR IGNORE INTO cluster_addresses
                (address, cluster_id, confidence, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?)
            """, (addr, base_cluster, 0.7, now, now))
            cluster_cache[addr] = (base_cluster, 0.7)

    # ======================================
    # Exchange deposit detection
    # ======================================
    if detect_exchange_deposit(inputs, outputs):
        out_addr = list(outputs.keys())[0]
        cid, _ = resolve_cluster(out_addr, cursor, cluster_cache)
        cid = _cid(cid)
        if not cid:
            cid = create_behavioral_cluster(out_addr, cursor, cluster_cache)
        execute_with_retry(cursor, """
            UPDATE clusters
            SET cluster_type=?, confidence=?
            WHERE id=?
        """, ("EXCHANGE", 0.9, cid))
        logger.info(f"[CLUSTER] Exchange deposit wallet {cid}")

    # ======================================
    # Fanout clustering (exchange hotwallet)
    # ======================================
    if not (len(inputs) == 1 and len(outputs) == 1):
        largest_output = max(outputs.values()) if outputs else 0
        num_outputs = len(outputs)
        if len(inputs) == 1 and 15 <= num_outputs <= 100 and total >= 50 and largest_output < total * 0.8:
            avg_output = total / num_outputs
            if largest_output > avg_output * 3:
                return  # skip fanout

            existing_clusters = set()
            for addr in outputs.keys():
                cid, _ = resolve_cluster(addr, cursor, cluster_cache)
                cid = _cid(cid)
                if cid:
                    existing_clusters.add(cid)

            base_cluster = min(existing_clusters) if existing_clusters else create_behavioral_cluster(list(outputs.keys())[0], cursor, cluster_cache)

            for addr in outputs.keys():
                execute_with_retry(cursor, """
                    INSERT OR IGNORE INTO cluster_addresses
                    (address, cluster_id, confidence, first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?)
                """, (addr, base_cluster, 0.5, now, now))
                cluster_cache[addr] = (base_cluster, 0.5)

    # ======================================
    # Hot wallet detection
    # ======================================
    if detect_hot_wallet(inputs, outputs):
        base_cluster = create_behavioral_cluster(list(outputs.keys())[0], cursor, cluster_cache)
        execute_with_retry(cursor, """
            UPDATE clusters
            SET cluster_type=?, confidence=?
            WHERE id=?
        """, ("EXCHANGE", 0.85, base_cluster))
        logger.info(f"[CLUSTER] Hot wallet detected {base_cluster}")

    # ======================================
    # Change address detection
    # ======================================
    change_addr = detect_change_address(inputs, outputs)
    if change_addr:
        in_addr = list(inputs.keys())[0]
        cid, _ = resolve_cluster(in_addr, cursor, cluster_cache)
        cid = _cid(cid)
        if cid:
            execute_with_retry(cursor, """
                INSERT OR IGNORE INTO cluster_addresses
                (address, cluster_id, confidence, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?)
            """, (change_addr, cid, 0.8, now, now))
            cluster_cache[change_addr] = (cid, 0.8)

    # ======================================
    # Peel chain clustering
    # ======================================
    peel_addr = detect_peel_chain(inputs, outputs)
    if peel_addr:
        in_addr = list(inputs.keys())[0]
        cid, _ = resolve_cluster(in_addr, cursor, cluster_cache)
        cid = _cid(cid)
        if cid:
            execute_with_retry(cursor, """
                INSERT OR IGNORE INTO cluster_addresses
                (address, cluster_id, confidence, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?)
            """, (peel_addr, cid, 0.85, now, now))
            cluster_cache[peel_addr] = (cid, 0.85)

    # ======================================
    # Multi-input clustering
    # ======================================
    input_addrs = list(inputs.keys())
    addr_to_cluster = {addr: _cid(resolve_cluster(addr, cursor, cluster_cache)[0]) for addr in input_addrs}

    if input_addrs and len(input_addrs) >= 3 and total >= 5:
        cluster_ids = list(set(cid for cid in addr_to_cluster.values() if cid))
        if len(cluster_ids) > 1:
            base = min(cluster_ids)
            for cid in cluster_ids:
                cid = _cid(cid)
                if cid != base:
                    merge_clusters(base, cid, cursor, cluster_cache)

        cluster_ids = [cid for cid in addr_to_cluster.values() if cid]
        base_cluster = min(cluster_ids) if cluster_ids else create_behavioral_cluster(input_addrs[0], cursor, cluster_cache)

        for addr in input_addrs:
            cid = addr_to_cluster[addr]
            if not cid:
                execute_with_retry(cursor, """
                    INSERT OR IGNORE INTO cluster_addresses
                    (address, cluster_id, confidence, first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?)
                """, (addr, base_cluster, 0.6, now, now))
                addr_to_cluster[addr] = base_cluster
                cluster_cache[addr] = (base_cluster, 0.6)
            else:
                update_address_seen(addr, cursor)

        for cid in set(addr_to_cluster.values()):
            cid = _cid(cid)
            cluster_type = _cluster_type_cache.get(cid)
            if not cluster_type:
                row = fetchone_with_retry(
                    cursor,
                    "SELECT cluster_type FROM clusters WHERE id=?",
                    (cid,)
                )
                cluster_type = row["cluster_type"] if row else None
                _cluster_type_cache[cid] = cluster_type
                if len(_cluster_type_cache) > CACHE_LIMIT:
                    _cluster_type_cache.popitem(last=False)
            if cluster_type == "BEHAVIORAL":
                upgrade_queue.add(cid)

    # ======================================
    # Update output address activity
    # ======================================
    for addr in outputs.keys():
        cid, _ = resolve_cluster(addr, cursor, cluster_cache)
        cid = _cid(cid)
        if cid:
            update_address_seen(addr, cursor)

    # ======================================
    # Flow classification
    # ======================================
    flows = classify_flow(inputs, outputs, cursor, cluster_cache)
    if not flows:
        flows = heuristic_flow_classification(inputs, outputs, total)
    # ===== FIX: deduplicate flows =====
    unique_flows = {}
    for f in flows:
        key = (f[0], f[1], f[2])  # (from_cluster, to_cluster, flow_type)
        unique_flows[key] = f
    
    flows = list(unique_flows.values())
    
    # Сохраняем общую транзакцию
    execute_with_retry(cursor, "INSERT OR IGNORE INTO whale_tx(txid, btc, time) VALUES (?,?,?)", (txid, total, now))
    
    # Определяем confidence
    confidence = 0.9 if len(inputs) == 1 and len(outputs) == 1 else 0.6 if len(inputs) > 1 or len(outputs) > 2 else 0.7
    
    # Сохраняем каждый поток безопасно через новую функцию
    for from_c, to_c, flow_type, flow_btc in flows:
        from_c = _cid(from_c)
        to_c = _cid(to_c)
    
        # FIX: normalize NULL early
        from_c = from_c if from_c is not None else -1
        to_c = to_c if to_c is not None else -1
    
        safe_insert_whale_classification(cursor, txid, flow_btc, now, from_c, to_c, flow_type, confidence)

        # Exchange flow aggregation (1h bucket)
        bucket = now - (now % 3600)
        if flow_type in ("DEPOSIT", "WITHDRAW", "INTERNAL") and flow_btc >= MIN_WHALE_BTC:
            cid = to_c if flow_type == "DEPOSIT" else from_c
            if cid:
                execute_with_retry(cursor, """
                    INSERT INTO exchange_flow (ts, cluster_id, flow_type, btc)
                    VALUES (?,?,?,?)
                    ON CONFLICT(ts, cluster_id, flow_type)
                    DO UPDATE SET btc = btc + excluded.btc
                """, (bucket, cid, flow_type, flow_btc))

        if flow_btc >= ALERT_WHALE_BTC:
            event = {"txid": txid, "btc": round(flow_btc, 4), "flow_type": flow_type,
                     "from_cluster": from_c, "to_cluster": to_c, "confidence": confidence, "time": now}
            _events.put(event)
            logger.info(f"[EVENT] Stored+Queued {txid} {flow_btc} BTC {flow_type}")

def safe_insert_whale_classification(cursor, txid, flow_btc, now, from_c, to_c, flow_type, confidence):
    """
    Безопасная вставка/апдейт whale_classification:
    - нет race condition (1 SQL вместо 2)
    - защита от NULL (используем -1)
    - работает с UNIQUE(txid, flow_type, from_cluster, to_cluster)
    """

    # ✅ нормализация NULL → обязательно
    from_c = from_c if from_c is not None else -1
    to_c = to_c if to_c is not None else -1

    retries = 3

    for _ in range(retries):
        try:
            execute_with_retry(cursor, """
                INSERT INTO whale_classification
                (txid, btc, time, from_cluster, to_cluster, flow_type, confidence)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(txid, flow_type, from_cluster, to_cluster)
                DO UPDATE SET
                    btc = excluded.btc,
                    time = excluded.time,
                    confidence = excluded.confidence
            """, (txid, flow_btc, now, from_c, to_c, flow_type, confidence))

            return  # ✅ успех — выходим сразу

        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                time.sleep(0.02)
            else:
                raise

    # если совсем не получилось
    raise sqlite3.OperationalError("Failed to insert/update whale_classification after retries")


# ==============================================
# WebSocket Worker
# ==============================================

async def mempool_ws_worker():
    while True:
        last_log = 0
        try:
            logger.info("[MEMPOOL] Connecting via WebSocket...")

            async with websockets.connect(
                MEMPOOL_WS,
                ping_interval=20,
                ping_timeout=10,
                max_size=None
            ) as ws:

                await ws.send(json.dumps({"track-mempool": True}))
                logger.info("[MEMPOOL] Subscribed to mempool")

                cluster_cache_session = {}

                with get_db() as conn:
                    c = conn.cursor()

                    async for raw in ws:
                        now_ts = time.time()

                        if now_ts - last_log > 120:
                            logger.info(f"[MEMPOOL] Alive. Seen txids: {len(_seen_txids)}")
                            last_log = now_ts

                        try:
                            data = json.loads(raw)
                        except Exception:
                            continue

                        txs = data.get("mempool-transactions", {}).get("added", [])
                        if not txs:
                            continue

                        # process each tx safely with retries
                        for tx in txs:
                            try:
                                process_tx(tx, c, cluster_cache_session)
                            except sqlite3.OperationalError as e:
                                logger.warning(f"[MEMPOOL] DB locked while processing tx {tx.get('txid')}: {e}")
                                # можно пропустить или повторить позже

                        # безопасный commit с retry
                        try:
                            conn.commit()
                        except sqlite3.OperationalError as e:
                            if "locked" in str(e).lower():
                                logger.warning("[MEMPOOL] Commit locked, will retry next batch")
                            else:
                                raise

        except Exception as e:
            logger.error(f"[MEMPOOL] WS error: {e}")
            await asyncio.sleep(5)