import time
import json
import asyncio
import websockets
import queue

from database.database import get_db
from config import Config
from logger import get_logger

logger = get_logger(__name__)

MIN_WHALE_BTC = Config.MIN_WHALE_BTC
ALERT_WHALE_BTC = Config.ALERT_WHALE_BTC
MEMPOOL_WS = "wss://mempool.space/api/v1/ws"
SATOSHI = 100_000_000

_events = queue.Queue()


def get_event_queue():
    return _events


# =====================================================
# Cluster resolution
# =====================================================

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


# =====================================================
# Parsing
# =====================================================

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


# =====================================================
# Flow classification
# =====================================================

def classify_flow(inputs, outputs, cursor):

    in_clusters = {}
    out_clusters = {}

    for addr, btc in inputs.items():
        cid, conf = resolve_cluster(addr, cursor)
        if cid:
            in_clusters[cid] = in_clusters.get(cid, 0) + btc

    for addr, btc in outputs.items():
        cid, conf = resolve_cluster(addr, cursor)
        if cid:
            out_clusters[cid] = out_clusters.get(cid, 0) + btc

    # INTERNAL
    for cid in in_clusters:
        if cid in out_clusters:
            return cid, cid, "INTERNAL", min(in_clusters[cid], out_clusters[cid])

    # DEPOSIT (входит в кластер)
    for cid in out_clusters:
        if cid not in in_clusters:
            return None, cid, "DEPOSIT", out_clusters[cid]

    # WITHDRAW (выходит из кластера)
    for cid in in_clusters:
        if cid not in out_clusters:
            return cid, None, "WITHDRAW", in_clusters[cid]

    return None, None, "UNKNOWN", 0


# =====================================================
# WebSocket
# =====================================================

async def mempool_ws_handler():
    while True:
        try:
            logger.info("[MEMPOOL] Connecting…")

            async with websockets.connect(
                MEMPOOL_WS,
                ping_interval=20,
                ping_timeout=10,
                max_size=None
            ) as ws:

                await ws.send(json.dumps({"track-mempool": True}))
                logger.info("[MEMPOOL] Subscribed")

                async for raw in ws:

                    try:
                        data = json.loads(raw)
                    except:
                        continue

                    txs = data.get("mempool-transactions", {}).get("added", [])
                    if not txs:
                        continue

                    db = get_db()
                    c = db.cursor()
                    now = int(time.time())

                    for tx in txs:

                        try:
                            txid = tx.get("txid")
                            if not txid:
                                continue

                            inputs = get_input_map(tx)
                            outputs = get_output_map(tx)
                            total = sum(outputs.values())

                            # =================================================
                            # LEARNING PART
                            # =================================================

                            if total >= MIN_WHALE_BTC:

                                # создаём кластеры только если tx крупная
                                for addr in list(inputs.keys()) + list(outputs.keys()):
                                    cid, conf = resolve_cluster(addr, c)
                                    if not cid:
                                        create_behavioral_cluster(addr, c)
                                    else:
                                        update_address_seen(addr, c)

                                from_c, to_c, flow_type, flow_btc = classify_flow(
                                    inputs, outputs, c
                                )

                                if flow_btc <= 0:
                                    flow_btc = total

                                # whale_tx
                                c.execute("""
                                    INSERT OR IGNORE INTO whale_tx(txid, btc, time)
                                    VALUES (?,?,?)
                                """, (txid, total, now))

                                # whale_classification
                                c.execute("""
                                    INSERT OR REPLACE INTO whale_classification
                                    (txid, btc, time, from_cluster, to_cluster, flow_type)
                                    VALUES (?,?,?,?,?,?)
                                """, (txid, flow_btc, now, from_c, to_c, flow_type))

                                db.commit()

                            # =================================================
                            # ALERT PART
                            # =================================================

                            if total >= ALERT_WHALE_BTC:

                                from_c, to_c, flow_type, flow_btc = classify_flow(
                                    inputs, outputs, c
                                )

                                if flow_btc <= 0:
                                    flow_btc = total

                                event = {
                                    "txid": txid,
                                    "btc": round(flow_btc, 4),
                                    "flow": flow_type,
                                    "from_cluster": from_c,
                                    "to_cluster": to_c,
                                    "time": now
                                }

                                _events.put(event)

                                logger.info(
                                    f"🚨 ALERT {flow_type} {flow_btc:.2f} BTC"
                                )

                        except Exception as e:
                            logger.exception(f"TX error {tx.get('txid')}: {e}")

                    db.close()

        except Exception as e:
            logger.exception(f"[MEMPOOL] WS error: {e}")
            await asyncio.sleep(5)