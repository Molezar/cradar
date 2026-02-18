import time
import json
import asyncio
import websockets
import queue

from database.database import get_db
from config import Config
from logger import get_logger

logger = get_logger(__name__)

MIN_WHALE_BTC = Config.MIN_WHALE_BTC          # for learning
ALERT_WHALE_BTC = Config.ALERT_WHALE_BTC      # for alerts
MEMPOOL_WS = "wss://mempool.space/api/v1/ws"
SATOSHI = 100_000_000

_events = queue.Queue()

def get_event_queue():
    return _events


# ================================
# Cluster & Exchange Resolution
# ================================

def get_cluster(address, cursor):
    r = cursor.execute("""
        SELECT ec.id as cluster,
               ec.exchange,
               ac.confidence
        FROM address_cluster ac
        JOIN exchange_clusters ec ON ec.id = ac.cluster_id
        WHERE ac.address = ?
    """, (address,)).fetchone()

    if not r:
        return None, None, 0

    return r["cluster"], r["exchange"], r["confidence"]


# ================================
# Exchange propagation engine
# ================================

def propagate_clusters(txid, inputs, outputs, cursor):
    involved = set()

    # detect known exchanges involved
    for addr in list(inputs.keys()) + list(outputs.keys()):
        _, ex, conf = get_cluster(addr, cursor)
        if ex and conf > 0.6:
            involved.add(ex)

    if not involved:
        return

    # learn all counterparties as part of those exchanges
    for addr in list(inputs.keys()) + list(outputs.keys()):
        for ex in involved:
            row = cursor.execute("""
                SELECT id FROM exchange_clusters WHERE exchange=?
            """, (ex,)).fetchone()

            if not row:
                continue

            cluster_id = row["id"]

            existing = cursor.execute("""
                SELECT cluster_id, confidence FROM address_cluster WHERE address=?
            """, (addr,)).fetchone()

            if existing:
                # same exchange → reinforce
                if existing["cluster_id"] == cluster_id:
                    cursor.execute("""
                        UPDATE address_cluster
                        SET confidence = MIN(1.0, confidence + 0.1)
                        WHERE address=?
                    """, (addr,))
                else:
                    # competing exchange → switch if weak
                    if existing["confidence"] < 0.6:
                        cursor.execute("""
                            UPDATE address_cluster
                            SET cluster_id=?, confidence=0.4
                            WHERE address=?
                        """, (cluster_id, addr))
            else:
                cursor.execute("""
                    INSERT INTO address_cluster(address, cluster_id, confidence)
                    VALUES (?,?,0.3)
                """, (addr, cluster_id))

            cursor.execute("""
                INSERT OR IGNORE INTO exchange_addresses(address, exchange, is_anchor, score)
                VALUES (?,?,0,0.3)
            """, (addr, ex))


# ================================
# Input / Output parsing
# ================================

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


# ================================
# Flow classification
# ================================

def classify_flow(inputs, outputs, cursor):
    ex_in = {}
    ex_out = {}

    for addr, btc in inputs.items():
        _, ex, conf = get_cluster(addr, cursor)
        if ex and conf > 0.6:
            ex_in[ex] = ex_in.get(ex, 0) + btc

    for addr, btc in outputs.items():
        _, ex, conf = get_cluster(addr, cursor)
        if ex and conf > 0.6:
            ex_out[ex] = ex_out.get(ex, 0) + btc

    if not ex_in and not ex_out:
        return None, "OTC", 0

    for ex in ex_in:
        if ex in ex_out:
            return ex, "INTERNAL", min(ex_in[ex], ex_out[ex])

    for ex in ex_out:
        if ex not in ex_in:
            return ex, "DEPOSIT", ex_out[ex]

    for ex in ex_in:
        if ex not in ex_out:
            return ex, "WITHDRAWAL", ex_in[ex]

    return None, "OTC", 0


# ================================
# WebSocket
# ================================

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

                            # store outputs
                            for addr, btc in outputs.items():
                                c.execute("""
                                    INSERT INTO tx_outputs(txid,address,btc)
                                    VALUES (?,?,?)
                                """, (txid, addr, btc))

                            # -------------------------------
                            # LEARNING
                            # -------------------------------
                            if total >= MIN_WHALE_BTC:
                                # 1) first learn clusters
                                propagate_clusters(txid, inputs, outputs, c)

                                # 2) then classify using updated clusters
                                exchange, flow_type, flow_btc = classify_flow(inputs, outputs, c)

                                c.execute("""
                                    INSERT OR IGNORE INTO whale_tx(txid, btc, time)
                                    VALUES (?,?,?)
                                """, (txid, total, now))

                                c.execute("""
                                    INSERT OR IGNORE INTO whale_classification
                                    (txid, flow_type, exchange, btc, time)
                                    VALUES (?,?,?,?,?)
                                """, (txid, flow_type, exchange, flow_btc, now))

                                if exchange:
                                    c.execute("""
                                        INSERT INTO exchange_flow_v2(ts, exchange, flow_type, btc)
                                        VALUES (?, ?, ?, ?)
                                        ON CONFLICT(ts, exchange, flow_type) DO UPDATE SET
                                        btc = btc + excluded.btc
                                    """, (now, exchange, flow_type, flow_btc))

                                db.commit()

                            # -------------------------------
                            # ALERTS
                            # -------------------------------
                            if total >= ALERT_WHALE_BTC:
                                exchange, flow_type, flow_btc = classify_flow(inputs, outputs, c)

                                if flow_btc <= 0:
                                    flow_btc = total

                                event = {
                                    "txid": txid,
                                    "btc": round(flow_btc, 4),
                                    "flow": flow_type if exchange else None,
                                    "exchange": exchange,
                                    "time": now
                                }

                                _events.put(event)

                                logger.info(
                                    f"🚨 ALERT {flow_type or 'WHALE'} {flow_btc:.2f} BTC {exchange or ''}"
                                )

                        except Exception as e:
                            logger.exception(f"TX error {tx.get('txid')}: {e}")

                    db.close()

        except Exception as e:
            logger.exception(f"[MEMPOOL] WS error: {e}")
            await asyncio.sleep(5)