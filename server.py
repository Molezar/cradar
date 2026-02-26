from flask import Flask, jsonify, send_from_directory, Response
from flask_cors import CORS
import os
import threading
import asyncio
import json
import time
import requests
import queue
import sqlite3

from config import Config
from database.database import get_db, init_db
from onchain import mempool_ws_worker, get_event_queue
from cluster_engine import run_cluster_expansion
from logger import get_logger

logger = get_logger(__name__)

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MINIAPP_DIR = os.path.join(BASE_DIR, "miniapp")

WINDOWS = [600, 3600]

# ==============================================
# BTC PRICE
# ==============================================

def fetch_btc_price():
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
            timeout=10
        )
        r.raise_for_status()
        return float(r.json()["price"])
    except Exception as e:
        logger.warning(f"Failed to fetch BTC price: {e}")
        return None


def price_sampler():
    while True:
        try:
            price = fetch_btc_price()
            if price:

                now = int(time.time())

                conn = None
                try:
                    conn = get_db()
                    c = conn.cursor()

                    c.execute("""
                        INSERT INTO btc_price(ts, price)
                        VALUES (?, ?)
                        ON CONFLICT(ts) DO UPDATE SET
                            price=excluded.price
                    """, (now, price))

                    conn.commit()

                finally:
                    if conn:
                        conn.close()

        except Exception:
            logger.exception("Price sampler error")

        time.sleep(30)


# ==============================================
# EXCHANGE FLOW SAMPLER
# ==============================================

async def exchange_flow_sampler():
    while True:
        try:
            now = int(time.time())
            since = now - 600

            conn = None
            try:
                conn = get_db()
                c = conn.cursor()

                c.execute("""
                    INSERT INTO exchange_flow (ts, cluster_id, flow_type, btc)
                    SELECT ?, to_cluster, 'DEPOSIT', SUM(btc)
                    FROM whale_classification
                    WHERE time > ? AND flow_type='DEPOSIT'
                    AND to_cluster IS NOT NULL
                    GROUP BY to_cluster
                    UNION ALL
                    SELECT ?, from_cluster, 'WITHDRAW', SUM(btc)
                    FROM whale_classification
                    WHERE time > ? AND flow_type='WITHDRAW'
                    AND from_cluster IS NOT NULL
                    GROUP BY from_cluster
                    ON CONFLICT(ts, cluster_id, flow_type)
                    DO UPDATE SET btc = excluded.btc
                """, (now, since, now, since))

                conn.commit()

            finally:
                if conn:
                    conn.close()

        except Exception:
            logger.exception("Exchange flow sampler error")

        await asyncio.sleep(60)


# ==============================================
# TRAINER
# ==============================================

async def trainer():
    while True:
        try:
            now = int(time.time())

            conn = None
            try:
                conn = get_db()
                c = conn.cursor()

                for w in WINDOWS:
                    rows = c.execute("""
                        SELECT ts, price
                        FROM btc_price
                        WHERE ts <= ?
                        AND ts >= ?
                        ORDER BY ts DESC
                    """, (now, now - w)).fetchall()

                    if not rows:
                        continue

                    p1 = rows[0]["price"]
                    p0 = rows[-1]["price"]

                    if not p0:
                        continue

                    dp = (p1 - p0) / p0

                    row = c.execute("""
                        SELECT
                            COALESCE(SUM(CASE WHEN flow_type='DEPOSIT' THEN btc END), 0) as buy,
                            COALESCE(SUM(CASE WHEN flow_type='WITHDRAW' THEN btc END), 0) as sell
                        FROM exchange_flow
                        WHERE ts > ?
                    """, (now - w,)).fetchone()

                    buy = row["buy"]
                    sell = row["sell"]
                    net_flow = buy - sell

                    value = dp / (abs(net_flow) + 1)

                    c.execute("""
                        INSERT INTO whale_correlation(window, weight, samples)
                        VALUES (?, ?, 1)
                        ON CONFLICT(window) DO UPDATE SET
                            weight = (
                                (whale_correlation.weight * whale_correlation.samples + excluded.weight)
                                / (whale_correlation.samples + 1)
                            ),
                            samples = whale_correlation.samples + 1
                    """, (w, value))

                conn.commit()

            finally:
                if conn:
                    conn.close()

        except Exception:
            logger.exception("Trainer error")

        await asyncio.sleep(300)


# ==============================================
# API
# ==============================================

@app.route("/whales")
def whales():
    conn = None
    try:
        conn = get_db()
        c = conn.cursor()

        rows = c.execute("""
            SELECT
                txid,
                btc,
                time,
                flow_type,
                from_cluster,
                to_cluster
            FROM whale_classification
            WHERE btc >= ?
            ORDER BY time DESC
            LIMIT 50
        """, (Config.MIN_WHALE_BTC,)).fetchall()

        result = [dict(r) for r in rows]

        return jsonify({
            "count": len(result),
            "whales": result
        })

    except Exception:
        logger.exception("Whales endpoint error")
        return jsonify({"error": "Internal server error"}), 500

    finally:
        if conn:
            conn.close()


@app.route("/price")
def price():
    conn = None
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT price FROM btc_price ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        return jsonify({"price": row["price"] if row else None})
    except Exception:
        logger.exception("Price endpoint error")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        if conn:
            conn.close()


@app.route("/prediction")
def prediction():
    conn = None
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT price FROM btc_price ORDER BY ts DESC LIMIT 1"
        ).fetchone()

        if not row:
            return jsonify({})

        price = row["price"]

        weights = conn.execute(
            "SELECT window, weight FROM whale_correlation WHERE window IN ({})".format(
                ",".join("?" * len(WINDOWS))
            ),
            WINDOWS
        ).fetchall()

        out = {}
        for r in weights:
            pct = r["weight"] * 100
            out[str(r["window"])] = {
                "pct": round(pct, 2),
                "target": round(price * (1 + pct / 100), 2)
            }

        return jsonify(out)

    except Exception:
        logger.exception("Prediction endpoint error")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        if conn:
            conn.close()


@app.route("/events")
def events():
    def stream():
        logger.info("[SSE] Client connected")
        conn = None
        try:
            conn = get_db()
            rows = conn.execute("""
                SELECT txid, btc, time, flow_type, from_cluster, to_cluster
                FROM alert_tx
                ORDER BY time DESC
                LIMIT 50
            """).fetchall()

            for r in reversed(rows):
                yield f"data: {json.dumps(dict(r))}\n\n"
        except Exception:
            logger.exception("[SSE] Failed to preload events")
        finally:
            if conn:
                conn.close()

        q = get_event_queue()
        while True:
            try:
                tx = q.get(timeout=10)
                yield f"data: {json.dumps(tx)}\n\n"
            except queue.Empty:
                yield ":\n\n"

    return Response(stream(), mimetype="text/event-stream")


@app.route("/")
def index():
    return send_from_directory(MINIAPP_DIR, "index.html")


@app.route("/<path:path>")
def files(path):
    return send_from_directory(MINIAPP_DIR, path)


# =====================================================
# STARTUP
# =====================================================

def clustering_loop():
    while True:
        try:
            run_cluster_expansion()
        except Exception:
            logger.exception("Cluster expansion error")
        time.sleep(1800)


def ensure_db():
    db_path = Config.DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if not db_path.exists():
        init_db()

    conn = sqlite3.connect(db_path)
    conn.close()


def start_async_tasks_loop():
    """Запускает все async задачи в одном лупе"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(exchange_flow_sampler())
    loop.create_task(trainer())
    loop.create_task(mempool_ws_worker())
    loop.run_forever()


if __name__ == "__main__":
    ensure_db()

    # Синхронные воркеры
    threading.Thread(target=clustering_loop, daemon=True).start()
    threading.Thread(target=price_sampler, daemon=True).start()

    # Все async задачи в одном лупе
    threading.Thread(target=start_async_tasks_loop, daemon=True).start()

    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=Config.DEBUG, threaded=True)