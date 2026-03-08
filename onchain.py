# onchain.py
import time
import json
import asyncio
import queue
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
_seen_txids = set()


def get_event_queue():
    return _events


# ==============================================
# Cluster resolution
# ==============================================

def resolve_cluster(address, cursor):
    r = cursor.execute("""
        SELECT cluster_id, confidence
        FROM cluster_addresses
        WHERE address=?
    """, (address,)).fetchone()

    if not r:
        return None, 0

    return r["cluster_id"], r["confidence"]


def update_address_seen(address, cursor):
    cursor.execute("""
        UPDATE cluster_addresses
        SET last_seen=?
        WHERE address=?
    """, (int(time.time()), address))


def create_behavioral_cluster(address, cursor):
    now = int(time.time())

    cursor.execute("""
        INSERT INTO clusters
        (cluster_type, confidence, size, created_at, last_updated)
        VALUES ('BEHAVIORAL', 0.4, 1, ?, ?)
    """, (now, now))

    cluster_id = cursor.lastrowid

    cursor.execute("""
        INSERT INTO cluster_addresses
        (address, cluster_id, confidence, first_seen, last_seen)
        VALUES (?, ?, 0.4, ?, ?)
    """, (address, cluster_id, now, now))

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


def store_tx_io(txid, inputs_map, outputs_map):
    conn = get_db()
    c = conn.cursor()

    input_rows = [
        (txid, addr, btc)
        for addr, btc in inputs_map.items()
    ]

    output_rows = [
        (txid, addr, btc)
        for addr, btc in outputs_map.items()
    ]

    c.executemany("""
        INSERT OR IGNORE INTO tx_inputs (txid, address, btc)
        VALUES (?, ?, ?)
    """, input_rows)

    c.executemany("""
        INSERT OR IGNORE INTO tx_outputs (txid, address, btc)
        VALUES (?, ?, ?)
    """, output_rows)

    conn.commit()
    conn.close()


# ==============================================
# Flow classification
# ==============================================

def classify_flow(inputs, outputs, cursor):

    in_exchange = {}
    out_exchange = {}

    for addr, btc in inputs.items():
        cid, _ = resolve_cluster(addr, cursor)
        if cid:
            row = cursor.execute(
                "SELECT cluster_type FROM clusters WHERE id=?",
                (cid,)
            ).fetchone()

            if row and row["cluster_type"] == "EXCHANGE":
                in_exchange[cid] = in_exchange.get(cid, 0) + btc

    for addr, btc in outputs.items():
        cid, _ = resolve_cluster(addr, cursor)
        if cid:
            row = cursor.execute(
                "SELECT cluster_type FROM clusters WHERE id=?",
                (cid,)
            ).fetchone()

            if row and row["cluster_type"] == "EXCHANGE":
                out_exchange[cid] = out_exchange.get(cid, 0) + btc

    flows = []

    total_in = sum(inputs.values())
    total_out = sum(outputs.values())

    if in_exchange and not out_exchange:
        for cid, vol in in_exchange.items():
            flows.append((cid, None, "WITHDRAW", vol))

    elif out_exchange and not in_exchange:
        for cid, vol in out_exchange.items():
            flows.append((None, cid, "DEPOSIT", vol))

    elif in_exchange and out_exchange:
        for cid, vol in in_exchange.items():
            flows.append((cid, None, "INTERNAL", vol))

    return flows

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

                async for raw in ws:

                    now_ts = time.time()
                    if now_ts - last_log > 120:
                        logger.info(f"[MEMPOOL] Alive. Seen txids: {len(_seen_txids)}")
                        last_log = now_ts

                    try:
                        data = json.loads(raw)
                    except:
                        continue

                    txs = data.get("mempool-transactions", {}).get("added", [])
                    if not txs:
                        continue

                    now = int(time.time())

                    for tx in txs:

                        txid = tx.get("txid")
                        if not txid or txid in _seen_txids:
                            continue

                        _seen_txids.add(txid)

                        # защита от роста памяти
                        if len(_seen_txids) > 200_000:
                            _seen_txids.clear()

                        inputs = get_input_map(tx)
                        outputs = get_output_map(tx)
                        total = sum(outputs.values())

                        if total < MIN_WHALE_BTC:
                            continue

                        store_tx_io(txid, inputs, outputs)

                        # --- DB WRITE BLOCK ---
                        conn = None
                        try:
                            conn = get_db()
                            c = conn.cursor()

                            # Кластеризация
                            for addr in list(inputs.keys()) + list(outputs.keys()):
                                cid, _ = resolve_cluster(addr, c)
                                if not cid:
                                    update_address_seen(addr, c)

                            flows = classify_flow(inputs, outputs, c)

                            # вставляем whale_tx ОДИН раз
                            c.execute("""
                                INSERT OR IGNORE INTO whale_tx(txid, btc, time)
                                VALUES (?,?,?)
                            """, (txid, total, now))

                            for from_c, to_c, flow_type, flow_btc in flows:

                                c.execute("""
                                    INSERT OR IGNORE INTO whale_classification
                                    (txid, btc, time, from_cluster, to_cluster, flow_type)
                                    VALUES (?,?,?,?,?,?)
                                """, (txid, flow_btc, now, from_c, to_c, flow_type))

                                if flow_btc >= ALERT_WHALE_BTC:
                                    c.execute("""
                                        INSERT INTO alert_tx
                                        (txid, btc, time, flow_type, from_cluster, to_cluster)
                                        VALUES (?,?,?,?,?,?)
                                    """, (txid, flow_btc, now, flow_type, from_c, to_c))

                                    event = {
                                        "txid": txid,
                                        "btc": round(flow_btc, 4),
                                        "flow": flow_type,
                                        "from_cluster": from_c,
                                        "to_cluster": to_c,
                                        "time": now
                                    }

                                    logger.info(f"[EVENT] Stored+Queued {txid} {flow_btc} BTC {flow_type}")
                                    _events.put(event)

                            conn.commit()

                        except Exception as db_error:
                            logger.error(f"[MEMPOOL][DB] {db_error}")

                        finally:
                            if conn:
                                conn.close()
                        # --- END DB BLOCK ---

        except Exception as e:
            logger.error(f"[MEMPOOL] WS error: {e}")
            await asyncio.sleep(5)