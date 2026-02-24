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
#MEMPOOL_WS = "wss://mempool.space/api/v1/ws"

_events = queue.Queue()
_seen_txids = set()


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

    # собираем входные объёмы
    for addr, btc in inputs.items():
        cid, _ = resolve_cluster(addr, cursor)
        if cid:
            in_clusters[cid] = in_clusters.get(cid, 0) + btc

    # собираем выходные объёмы
    for addr, btc in outputs.items():
        cid, _ = resolve_cluster(addr, cursor)
        if cid:
            out_clusters[cid] = out_clusters.get(cid, 0) + btc

    all_clusters = set(in_clusters.keys()) | set(out_clusters.keys())

    best_cluster = None
    best_net = 0

    for cid in all_clusters:
        in_vol = in_clusters.get(cid, 0)
        out_vol = out_clusters.get(cid, 0)

        net = out_vol - in_vol  # положительное = депозит

        if abs(net) > abs(best_net):
            best_net = net
            best_cluster = cid

    if not best_cluster:
        return None, None, "UNKNOWN", 0

    in_vol = in_clusters.get(best_cluster, 0)
    out_vol = out_clusters.get(best_cluster, 0)

    # INTERNAL если почти равны (5%)
    if max(in_vol, out_vol) > 0 and abs(in_vol - out_vol) / max(in_vol, out_vol) < 0.05:
        flow_type = "INTERNAL"
        flow_btc = min(in_vol, out_vol)
        return best_cluster, best_cluster, flow_type, flow_btc

    if best_net > 0:
        # деньги пришли в кластер
        return None, best_cluster, "DEPOSIT", abs(best_net)

    else:
        # деньги ушли из кластера
        return best_cluster, None, "WITHDRAW", abs(best_net)

# =====================================================
# WebSocket Worker
# =====================================================

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

                    db = get_db()
                    c = db.cursor()
                    now = int(time.time())

                    for tx in txs:

                        txid = tx.get("txid")
                        if not txid or txid in _seen_txids:
                            continue

                        _seen_txids.add(txid)

                        inputs = get_input_map(tx)
                        outputs = get_output_map(tx)
                        total = sum(outputs.values())

                        if total < MIN_WHALE_BTC:
                            continue

                        for addr in list(inputs.keys()) + list(outputs.keys()):
                            cid, _ = resolve_cluster(addr, c)
                            if not cid:
                                create_behavioral_cluster(addr, c)
                            else:
                                update_address_seen(addr, c)

                        from_c, to_c, flow_type, flow_btc = classify_flow(
                            inputs, outputs, c
                        )

                        if flow_type == "UNKNOWN":
                            continue

                        c.execute("""
                            INSERT OR IGNORE INTO whale_tx(txid, btc, time)
                            VALUES (?,?,?)
                        """, (txid, total, now))

                        c.execute("""
                            INSERT OR REPLACE INTO whale_classification
                            (txid, btc, time, from_cluster, to_cluster, flow_type)
                            VALUES (?,?,?,?,?,?)
                        """, (txid, flow_btc, now, from_c, to_c, flow_type))

                        if flow_btc >= ALERT_WHALE_BTC:
                            event = {
                                "txid": txid,
                                "btc": round(flow_btc, 4),
                                "flow": flow_type,
                                "from_cluster": from_c,
                                "to_cluster": to_c,
                                "time": now
                            }
                            logger.info(f"[EVENT] Queued {txid} {flow_btc} BTC {flow_type}")
                            _events.put(event)

                    db.commit()
                    db.close()

        except Exception as e:
            logger.error(f"[MEMPOOL] WS error: {e}")
            await asyncio.sleep(5)