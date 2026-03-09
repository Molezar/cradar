# onchain.py
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
        VALUES ('BEHAVIORAL', 0.4, 1, ?, ?)
    """, (now, now))
    cluster_id = cursor.lastrowid
    cursor.execute("""
        INSERT OR IGNORE INTO cluster_addresses
        (address, cluster_id, confidence, first_seen, last_seen)
        VALUES (?, ?, 0.4, ?, ?)
    """, (address, cluster_id, now, now))
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
    for txid in txids:
        inputs = cursor.execute("SELECT address FROM tx_inputs WHERE txid=?", (txid,)).fetchall()
        if len(inputs) > 1:
            multi_input_count += 1
        outputs = cursor.execute("SELECT address FROM tx_outputs WHERE txid=?", (txid,)).fetchall()
        if len(outputs) > 2:
            sweep_count += 1

    if multi_input_count >= 3 or sweep_count >= 3:
        cursor.execute("""
            UPDATE clusters
            SET cluster_type='EXCHANGE',
                confidence=0.9,
                last_updated=?
            WHERE id=?
        """, (now, cluster_id))
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
        if cid:
            row = cursor.execute("SELECT cluster_type FROM clusters WHERE id=?", (cid,)).fetchone()
            if row and row["cluster_type"] == "EXCHANGE":
                in_exchange[cid] = in_exchange.get(cid, 0) + btc
        else:
            unknown_inputs[addr] = btc

    for addr, btc in outputs.items():
        cid = cluster_cache.get(addr)
        if not cid:
            cid, _ = resolve_cluster(addr, cursor, cluster_cache)
        if cid:
            row = cursor.execute("SELECT cluster_type FROM clusters WHERE id=?", (cid,)).fetchone()
            if row and row["cluster_type"] == "EXCHANGE":
                out_exchange[cid] = out_exchange.get(cid, 0) + btc
        else:
            unknown_outputs[addr] = btc

    flows = []

    for cid, vol in in_exchange.items():
        if unknown_outputs:
            flows.append((cid, None, "WITHDRAW", vol))
    for cid, vol in out_exchange.items():
        if unknown_inputs:
            flows.append((None, cid, "DEPOSIT", vol))
    for cid_in, vol in in_exchange.items():
        for cid_out in out_exchange:
            flows.append((cid_in, cid_out, "INTERNAL", vol))
    return flows


def heuristic_flow_classification(inputs, outputs, total_btc):
    flows = []
    num_in = len(inputs)
    num_out = len(outputs)
    LARGE_TX_THRESHOLD = 10  # BTC

    if num_in == 1 and num_out > 1 and total_btc >= LARGE_TX_THRESHOLD:
        flows.append((None, None, "POSSIBLE_EXCHANGE_WITHDRAW", total_btc))
    elif num_in > 1 and num_out == 1 and total_btc >= LARGE_TX_THRESHOLD:
        flows.append((None, None, "POSSIBLE_EXCHANGE_DEPOSIT", total_btc))
    elif num_in > 1 and num_out > 1:
        flows.append((None, None, "INTERNAL", total_btc))
    else:
        flows.append((None, None, "TRANSFER", total_btc))
    return flows


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
        addr_to_cluster[addr] = cid

    if input_addrs and len(input_addrs) >= 2 and total >= 20:
        cluster_ids = [cid for cid in addr_to_cluster.values() if cid]
        if cluster_ids:
            base_cluster = min(cluster_ids)
        else:
            base_cluster = create_behavioral_cluster(input_addrs[0], cursor, cluster_cache)

        for addr in input_addrs:
            cid = addr_to_cluster[addr]
            if not cid:
                cursor.execute("""
                    INSERT OR IGNORE INTO cluster_addresses
                    (address, cluster_id, confidence, first_seen, last_seen)
                    VALUES (?, ?, 0.6, ?, ?)
                """, (addr, base_cluster, now, now))
                addr_to_cluster[addr] = base_cluster
                cluster_cache[addr] = (base_cluster, 0.6)
            else:
                update_address_seen(addr, cursor)

        cluster_ids_set = set(addr_to_cluster.values())
        for cid in cluster_ids_set:
            row = cursor.execute("SELECT cluster_type FROM clusters WHERE id=?", (cid,)).fetchone()
            if row and row["cluster_type"] == "BEHAVIORAL":
                behavioral_to_exchange(cid, cursor, now)

    for addr in outputs.keys():
        cid, _ = resolve_cluster(addr, cursor, cluster_cache)
        if cid:
            update_address_seen(addr, cursor)

    flows = classify_flow(inputs, outputs, cursor, cluster_cache)
    if all(f[2] == "UNCLASSIFIED" for f in flows):
        flows = heuristic_flow_classification(inputs, outputs, total)
    if not flows:
        flows = [(None, None, "UNCLASSIFIED", total)]

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
        cursor.execute("""
            INSERT OR IGNORE INTO whale_classification
            (txid, btc, time, from_cluster, to_cluster, flow_type, confidence)
            VALUES (?,?,?,?,?,?,?)
        """, (txid, flow_btc, now, from_c, to_c, flow_type, confidence))

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
            logger.info(f"[EVENT] Stored+Queued {txid} {flow_btc} BTC {flow_type}")


# ==============================================
# WebSocket Worker
# ==============================================

async def mempool_ws_worker():
    while True:
        last_log = 0
        try:
            logger.info("[MEMPOOL] Connecting via WebSocket...")
            async with websockets.connect(MEMPOOL_WS, ping_interval=20, ping_timeout=10, max_size=None) as ws:
                await ws.send(json.dumps({"track-mempool": True}))
                logger.info("[MEMPOOL] Subscribed to mempool")

                cluster_cache_session = {}  # <-- глобальный кэш для текущей WS-сессии

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

                        for tx in txs:
                            process_tx(tx, c, cluster_cache_session)
                    conn.commit()

        except Exception as e:
            logger.error(f"[MEMPOOL] WS error: {e}")
            await asyncio.sleep(5)