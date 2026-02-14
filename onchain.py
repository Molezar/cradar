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
MEMPOOL_WS = "wss://mempool.space/api/v1/ws"
SATOSHI = 100_000_000

_events = queue.Queue()


def get_event_queue():
    return _events


async def mempool_ws_handler():
    while True:
        try:
            logger.info("[MEMPOOL] Connecting…")

            async with websockets.connect(MEMPOOL_WS, ping_interval=20) as ws:
                await ws.send(json.dumps({"track-mempool": True}))
                logger.info("[MEMPOOL] Subscribed to mempool transactions")

                async for raw in ws:
                    try:
                        data = json.loads(raw)
                    except Exception as e:
                        logger.warning(f"[MEMPOOL] Failed to parse JSON: {e}")
                        continue

                    txs = data.get("mempool-transactions", {}).get("added", [])
                    if not txs:
                        continue

                    conn = get_db()
                    c = conn.cursor()
                    now = int(time.time())

                    for tx in txs:
                        try:
                            txid = tx.get("txid")
                            if not txid:
                                continue

                            vouts = tx.get("vout", [])
                            total = sum(v["value"] for v in vouts) / SATOSHI

                            if total < MIN_WHALE_BTC:
                                continue

                            # === Save whale tx ===
                            c.execute(
                                "INSERT OR IGNORE INTO whale_tx (txid, btc, time) VALUES (?, ?, ?)",
                                (txid, total, now)
                            )

                            # === Save outputs & addresses ===
                            for v in vouts:
                                addr = v.get("scriptpubkey_address")
                                if not addr:
                                    continue

                                btc = v["value"] / SATOSHI

                                c.execute("""
                                INSERT OR IGNORE INTO addresses(address, first_seen, last_seen, total_btc)
                                VALUES (?, ?, ?, 0)
                                """, (addr, now, now))

                                c.execute("""
                                UPDATE addresses
                                SET last_seen=?, total_btc=total_btc+?
                                WHERE address=?
                                """, (now, btc, addr))

                                c.execute(
                                    "INSERT INTO tx_outputs (txid, address, btc) VALUES (?,?,?)",
                                    (txid, addr, btc)
                                )

                            conn.commit()

                            whale = {
                                "txid": txid,
                                "btc": round(total, 6),
                                "time": now
                            }

                            _events.put(whale)
                            logger.info(f"🐋 Whale detected: {whale['btc']} BTC tx {txid[:12]}…")

                        except Exception as e:
                            logger.exception(f"TX parse error for txid {tx.get('txid')}: {e}")

                    conn.close()

        except Exception as e:
            logger.exception(f"[MEMPOOL] WS error: {e}")
            await asyncio.sleep(5)