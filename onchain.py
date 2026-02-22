import time
import json
import asyncio
import queue
import requests

from database.database import get_db
from config import Config
from logger import get_logger

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = get_logger(__name__)

MIN_WHALE_BTC = Config.MIN_WHALE_BTC
ALERT_WHALE_BTC = Config.ALERT_WHALE_BTC
SATOSHI = 100_000_000

MEMPOOL_RECENT = "https://mempool.space/api/mempool/recent"

_events = queue.Queue()
_seen_txids = set()

# ---------- Safe REST session ----------

session = requests.Session()
retries = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
)
session.mount("https://", HTTPAdapter(max_retries=retries))


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
        cid, _ = resolve_cluster(addr, cursor)
        if cid:
            in_clusters[cid] = in_clusters.get(cid, 0) + btc

    for addr, btc in outputs.items():
        cid, _ = resolve_cluster(addr, cursor)
        if cid:
            out_clusters[cid] = out_clusters.get(cid, 0) + btc

    for cid in in_clusters:
        if cid in out_clusters:
            return cid, cid, "INTERNAL", min(in_clusters[cid], out_clusters[cid])

    for cid in out_clusters:
        if cid not in in_clusters:
            return None, cid, "DEPOSIT", out_clusters[cid]

    for cid in in_clusters:
        if cid not in out_clusters:
            return cid, None, "WITHDRAW", in_clusters[cid]

    return None, None, "UNKNOWN", 0


# =====================================================
# REST Polling Engine
# =====================================================

def fetch_recent_mempool():
    try:
        r = session.get(MEMPOOL_RECENT, timeout=20)

        if r.status_code == 429:
            logger.warning("[MEMPOOL] 429 rate limit hit")
            return []

        if r.status_code != 200:
            return []

        return r.json()

    except Exception as e:
        logger.warning(f"[MEMPOOL] REST error: {e}")
        return []


async def mempool_rest_worker():

    interval = 20  # 20 seconds polling (safe)
    backoff = 20

    while True:

        try:

            txs = fetch_recent_mempool()

            if not txs:
                await asyncio.sleep(interval)
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

                if flow_btc <= 0:
                    flow_btc = total

                c.execute("""
                    INSERT OR IGNORE INTO whale_tx(txid, btc, time)
                    VALUES (?,?,?)
                """, (txid, total, now))

                c.execute("""
                    INSERT OR REPLACE INTO whale_classification
                    (txid, btc, time, from_cluster, to_cluster, flow_type)
                    VALUES (?,?,?,?,?,?)
                """, (txid, flow_btc, now, from_c, to_c, flow_type))

                if total >= ALERT_WHALE_BTC:
                    event = {
                        "txid": txid,
                        "btc": round(flow_btc, 4),
                        "flow": flow_type,
                        "from_cluster": from_c,
                        "to_cluster": to_c,
                        "time": now
                    }
                    _events.put(event)

            db.commit()
            db.close()

            backoff = interval  # reset if success

        except Exception as e:
            logger.exception(f"[MEMPOOL] Worker error: {e}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 120)

        await asyncio.sleep(interval)