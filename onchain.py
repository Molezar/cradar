#onchain.py
import time
import json
import asyncio
import queue
from collections import deque
import websockets

from database.database import get_db
from config import Config
from logger import get_logger

logger = get_logger(__name__)

MIN_WHALE_BTC = Config.MIN_WHALE_BTC
ALERT_WHALE_BTC = Config.ALERT_WHALE_BTC
SATOSHI = 100_000_000
MEMPOOL_WS = "wss://mempool.emzy.de/api/v1/ws"

_events = queue.Queue()
_seen_txids = deque(maxlen=100_000)


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

    r = cursor.execute("""
        SELECT cluster_id, confidence
        FROM cluster_addresses
        WHERE address=?
    """, (address,)).fetchone()

    result = (r["cluster_id"], r["confidence"]) if r else (None, 0)

    if cache is not None:
        cache[address] = result

    return result


def update_address_seen(address, cursor):
    cursor.execute("""
        UPDATE cluster_addresses
        SET last_seen=?
        WHERE address=?
    """, (int(time.time()), address))


def create_behavioral_cluster(address, cursor, cache=None):
    now = int(time.time())

    cursor.execute("""
        INSERT INTO clusters
        (cluster_type, confidence, size, created_at, last_updated)
        VALUES (?, ?, ?, ?, ?)
    """, ("BEHAVIORAL", 0.4, 1, now, now))

    cluster_id = cursor.lastrowid

    cursor.execute("""
        INSERT OR IGNORE INTO cluster_addresses
        (address, cluster_id, confidence, first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?)
    """, (address, cluster_id, 0.4, now, now))

    if cache is not None:
        cache[address] = (cluster_id, 0.4)

    return cluster_id


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

    cursor.executemany("""
        INSERT OR IGNORE INTO tx_inputs (txid, address, btc)
        VALUES (?, ?, ?)
    """, input_rows)

    cursor.executemany("""
        INSERT OR IGNORE INTO tx_outputs (txid, address, btc)
        VALUES (?, ?, ?)
    """, output_rows)


# ==============================================
# Behavioral -> Exchange upgrade
# ==============================================

def behavioral_to_exchange(cluster_id, cursor, now):

    lookback = now - (30 * 24 * 3600)

    rows = cursor.execute("""
        SELECT txid
        FROM whale_classification
        WHERE time > ? AND (from_cluster=? OR to_cluster=?)
    """, (lookback, cluster_id, cluster_id)).fetchall()

    if not rows:
        return False

    txids = [r["txid"] for r in rows]

    multi_input_count = 0
    sweep_count = 0
    fanout_count = 0
    deposit_pattern = 0

    for txid in txids:

        inputs = cursor.execute(
            "SELECT address FROM tx_inputs WHERE txid=?",
            (txid,)
        ).fetchall()

        if len(inputs) > 1:
            multi_input_count += 1

        outputs = cursor.execute(
            "SELECT address FROM tx_outputs WHERE txid=?",
            (txid,)
        ).fetchall()

        if len(outputs) > 2:
            sweep_count += 1
            
        if len(outputs) >= 10:
            fanout_count += 1
            
        if len(inputs) >= 3 and len(outputs) == 1:
            deposit_pattern += 1

    if (
        multi_input_count >= 5
        or sweep_count >= 5
        or fanout_count >= 3
        or deposit_pattern >= 5
    ):

        cursor.execute("""
            UPDATE clusters
            SET cluster_type=?, confidence=?, last_updated=?
            WHERE id=?
        """, ("EXCHANGE", 0.9, now, cluster_id))

        logger.info(f"[CLUSTER] Behavioral cluster {cluster_id} upgraded to EXCHANGE")

        return True

    return False


# ==============================================
# Flow classification
# ==============================================

def classify_flow(inputs, outputs, cursor, cache=None):

    in_exchange = {}
    out_exchange = {}
    unknown_inputs = {}
    unknown_outputs = {}

    cluster_cache = cache if cache is not None else {}

    for addr, btc in inputs.items():

        cid, _ = resolve_cluster(addr, cursor, cluster_cache)
        cid = _cid(cid)

        if cid:
            row = cursor.execute(
                "SELECT cluster_type FROM clusters WHERE id=?",
                (cid,)
            ).fetchone()

            if row and row["cluster_type"] == "EXCHANGE":
                in_exchange[cid] = in_exchange.get(cid, 0) + btc
        else:
            unknown_inputs[addr] = btc

    for addr, btc in outputs.items():

        cached = cluster_cache.get(addr)

        if cached:
            cid = _cid(cached[0])
        else:
            cid, _ = resolve_cluster(addr, cursor, cluster_cache)
            cid = _cid(cid)

        if cid:
            row = cursor.execute(
                "SELECT cluster_type FROM clusters WHERE id=?",
                (cid,)
            ).fetchone()

            if row and row["cluster_type"] == "EXCHANGE":
                out_exchange[cid] = out_exchange.get(cid, 0) + btc
        else:
            unknown_outputs[addr] = btc

    flows = []

    for cid, vol in in_exchange.items():

        if unknown_outputs and is_exchange_withdraw(outputs):
    
            largest = max(outputs.values())
    
            flows.append((cid, None, "WITHDRAW", largest))

    for cid, vol in out_exchange.items():

        if unknown_inputs and not is_exchange_withdraw(outputs):
    
            flows.append((None, cid, "DEPOSIT", vol))

    for cid_in, vol in in_exchange.items():
        for cid_out in out_exchange:
            flows.append((cid_in, cid_out, "INTERNAL", vol))

    return flows

def heuristic_flow_classification(inputs, outputs, total_btc):

    flows = []

    num_in = len(inputs)
    num_out = len(outputs)

    largest_output = max(outputs.values())
    output_ratio = largest_output / total_btc if total_btc else 0

    LARGE_TX_THRESHOLD = 10

    # exchange withdraw pattern
    if num_in <= 2 and num_out >= 2 and output_ratio > 0.7:
        flows.append((None, None, "POSSIBLE_EXCHANGE_WITHDRAW", largest_output))

    # exchange deposit pattern
    elif num_in >= 3 and num_out <= 2:
        flows.append((None, None, "POSSIBLE_EXCHANGE_DEPOSIT", total_btc))

    # consolidation
    elif num_in >= 5 and num_out <= 2:
        flows.append((None, None, "CONSOLIDATION", total_btc))

    elif num_in > 1 and num_out > 1:
        flows.append((None, None, "INTERNAL", total_btc))

    else:
        flows.append((None, None, "TRANSFER", total_btc))

    return flows

def is_exchange_withdraw(outputs):

    vals = list(outputs.values())

    if len(vals) < 2:
        return False

    largest = max(vals)
    second = sorted(vals)[-2]

    if largest > second * 3:
        return True

    return False


# ==============================================
# TX processing
# ==============================================

def process_tx(tx, cursor, cluster_cache):

    txid = tx.get("txid")

    if not txid or txid in _seen_txids:
        return

    _seen_txids.append(txid)

    inputs = get_input_map(tx)
    outputs = get_output_map(tx)

    total = sum(outputs.values())

    if total < MIN_WHALE_BTC:
        return

    store_tx_io(txid, inputs, outputs, cursor)

    now = int(time.time())

    input_addrs = list(inputs.keys())
    addr_to_cluster = {}

    for addr in input_addrs:

        cid, _ = resolve_cluster(addr, cursor, cluster_cache)
        cid = _cid(cid)

        addr_to_cluster[addr] = cid

    if input_addrs and len(input_addrs) >= 2 and total >= 5:

        cluster_ids = [cid for cid in addr_to_cluster.values() if cid]

        if cluster_ids:
            base_cluster = min(cluster_ids)
        else:
            base_cluster = create_behavioral_cluster(
                input_addrs[0], cursor, cluster_cache
            )

        for addr in input_addrs:

            cid = addr_to_cluster[addr]

            if not cid:

                cursor.execute("""
                    INSERT OR IGNORE INTO cluster_addresses
                    (address, cluster_id, confidence, first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?)
                """, (addr, base_cluster, 0.6, now, now))

                addr_to_cluster[addr] = base_cluster
                cluster_cache[addr] = (base_cluster, 0.6)

            else:
                update_address_seen(addr, cursor)

        cluster_ids_set = set(addr_to_cluster.values())

        for cid in cluster_ids_set:

            cid = _cid(cid)

            row = cursor.execute(
                "SELECT cluster_type FROM clusters WHERE id=?",
                (cid,)
            ).fetchone()

            if row and row["cluster_type"] == "BEHAVIORAL":
                behavioral_to_exchange(cid, cursor, now)

    for addr in outputs.keys():

        cid, _ = resolve_cluster(addr, cursor, cluster_cache)
        cid = _cid(cid)

        if cid:
            update_address_seen(addr, cursor)

    flows = classify_flow(inputs, outputs, cursor, cluster_cache)

    if not flows:
        flows = heuristic_flow_classification(inputs, outputs, total)

    cursor.execute("""
        INSERT OR IGNORE INTO whale_tx(txid, btc, time)
        VALUES (?,?,?)
    """, (txid, total, now))

    if len(inputs) == 1 and len(outputs) == 1:
        confidence = 0.9
    elif len(inputs) > 1 or len(outputs) > 2:
        confidence = 0.6
    else:
        confidence = 0.7

    for from_c, to_c, flow_type, flow_btc in flows:

        from_c = _cid(from_c)
        to_c = _cid(to_c)

        cursor.execute("""
            INSERT OR IGNORE INTO whale_classification
            (txid, btc, time, from_cluster, to_cluster, flow_type, confidence)
            VALUES (?,?,?,?,?,?,?)
        """, (txid, flow_btc, now, from_c, to_c, flow_type, confidence))

        # ======================================
        # Exchange flow aggregation (1h bucket)
        # ======================================
        bucket = now - (now % 3600)

        if flow_type in ("DEPOSIT", "WITHDRAW", "INTERNAL"):

            if flow_type == "DEPOSIT":
                cid = to_c
        
            elif flow_type == "WITHDRAW":
                cid = from_c
        
            else:  # INTERNAL
                cid = from_c

            if cid:
                cursor.execute("""
                    INSERT INTO exchange_flow (ts, cluster_id, flow_type, btc)
                    VALUES (?,?,?,?)
                    ON CONFLICT(ts, cluster_id, flow_type)
                    DO UPDATE SET btc = btc + excluded.btc
                """, (bucket, cid, flow_type, flow_btc))
        
        if flow_btc >= ALERT_WHALE_BTC:

            event = {
                "txid": txid,
                "btc": round(flow_btc, 4),
                "flow_type": flow_type,
                "from_cluster": from_c,
                "to_cluster": to_c,
                "confidence": confidence,
                "time": now
            }

            _events.put(event)

            logger.info(
                f"[EVENT] Stored+Queued {txid} {flow_btc} BTC {flow_type}"
            )


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
                            logger.info(
                                f"[MEMPOOL] Alive. Seen txids: {len(_seen_txids)}"
                            )
                            last_log = now_ts

                        try:
                            data = json.loads(raw)
                        except Exception:
                            continue

                        txs = data.get("mempool-transactions", {}).get("added", [])

                        if not txs:
                            continue

                        for tx in txs:
                            process_tx(tx, c, cluster_cache_session)

                        conn.commit()

        except Exception as e:

            logger.error(f"[MEMPOOL] WS error: {e}")

            await asyncio.sleep(5)