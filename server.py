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

# =====================================================
# BTC PRICE
# =====================================================

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
                db = get_db()
                db.execute(
                    "INSERT OR REPLACE INTO btc_price(ts, price) VALUES (?,?)",
                    (int(time.time()), price)
                )
                db.commit()
                db.close()
        except Exception:
            logger.exception("Price sampler error")

        time.sleep(30)


# =====================================================
# EXCHANGE FLOW SAMPLER
# =====================================================

def exchange_flow_sampler():
    while True:
        try:
            now = int(time.time())
            since = now - 600

            db = get_db()
            c = db.cursor()

            rows = c.execute("""
                SELECT to_cluster as cluster_id, 'DEPOSIT' as flow_type, SUM(btc) as total
                FROM whale_classification
                WHERE time > ? AND flow_type='DEPOSIT'
                GROUP BY to_cluster

                UNION ALL

                SELECT from_cluster as cluster_id, 'WITHDRAW' as flow_type, SUM(btc) as total
                FROM whale_classification
                WHERE time > ? AND flow_type='WITHDRAW'
                GROUP BY from_cluster
            """, (since, since)).fetchall()

            for r in rows:
                if not r["cluster_id"]:
                    continue

                c.execute("""
                    INSERT OR REPLACE INTO exchange_flow
                    (ts, cluster_id, flow_type, btc)
                    VALUES (?,?,?,?)
                """, (now, r["cluster_id"], r["flow_type"], r["total"] or 0))

            db.commit()
            db.close()

        except Exception:
            logger.exception("Exchange flow sampler error")

        time.sleep(60)


# =====================================================
# TRAINER
# =====================================================

def trainer():
    while True:
        try:
            db = get_db()
            c = db.cursor()

            for w in WINDOWS:
                now = int(time.time())

                p1 = c.execute(
                    "SELECT price FROM btc_price WHERE ts <= ? ORDER BY ts DESC LIMIT 1",
                    (now,)
                ).fetchone()

                p0 = c.execute(
                    "SELECT price FROM btc_price WHERE ts <= ? ORDER BY ts DESC LIMIT 1",
                    (now - w,)
                ).fetchone()

                if not p0 or not p1:
                    continue

                dp = (p1["price"] - p0["price"]) / p0["price"]

                row = c.execute("""
                    SELECT
                        SUM(CASE WHEN flow_type='DEPOSIT' THEN btc ELSE 0 END) as buy,
                        SUM(CASE WHEN flow_type='WITHDRAW' THEN btc ELSE 0 END) as sell
                    FROM exchange_flow
                    WHERE ts > ?
                """, (now - w,)).fetchone()

                buy = row["buy"] or 0
                sell = row["sell"] or 0
                net_flow = buy - sell

                corr = c.execute(
                    "SELECT weight, samples FROM whale_correlation WHERE window=?",
                    (w,)
                ).fetchone()

                value = dp / (abs(net_flow) + 1)

                if corr:
                    weight = corr["weight"]
                    samples = corr["samples"]
                    new_weight = (weight * samples + value) / (samples + 1)

                    c.execute(
                        "UPDATE whale_correlation SET weight=?, samples=? WHERE window=?",
                        (new_weight, samples + 1, w)
                    )
                else:
                    c.execute(
                        "INSERT INTO whale_correlation(window, weight, samples) VALUES (?,?,1)",
                        (w, value)
                    )

            db.commit()
            db.close()

        except Exception:
            logger.exception("Trainer error")

        time.sleep(300)


# =====================================================
# API
# =====================================================

@app.route("/whales")
def whales():
    try:
        db = get_db()

        rows = db.execute("""
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

        db.close()

        return jsonify({
            "count": len(rows),
            "whales": [dict(r) for r in rows]
        })

    except Exception:
        logger.exception("Whales endpoint error")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/price")
def price():
    try:
        db = get_db()
        r = db.execute(
            "SELECT price FROM btc_price ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        db.close()
        return jsonify({"price": r["price"] if r else None})
    except Exception:
        logger.exception("Price endpoint error")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/prediction")
def prediction():
    try:
        db = get_db()

        price_row = db.execute(
            "SELECT price FROM btc_price ORDER BY ts DESC LIMIT 1"
        ).fetchone()

        if not price_row:
            return jsonify({})

        price = price_row["price"]
        out = {}

        for w in WINDOWS:
            r = db.execute(
                "SELECT weight FROM whale_correlation WHERE window=?",
                (w,)
            ).fetchone()

            if not r:
                continue

            pct = r["weight"] * 100

            out[str(w)] = {
                "pct": round(pct, 2),
                "target": round(price * (1 + pct / 100), 2)
            }

        db.close()
        return jsonify(out)

    except Exception:
        logger.exception("Prediction endpoint error")
        return jsonify({"error": "Internal server error"}), 500

@app.route("/events")
def events():

    def stream():
        logger.info("[SSE] Client connected")

        # 1️⃣ Сначала отдать последние 50 событий из БД
        try:
            db = get_db()
            rows = db.execute("""
                SELECT txid, btc, time, flow_type, from_cluster, to_cluster
                FROM alert_tx
                ORDER BY time DESC
                LIMIT 50
            """).fetchall()
            db.close()

            for r in reversed(rows):
                event = dict(r)
                yield f"data: {json.dumps(event)}\n\n"

        except Exception:
            logger.exception("[SSE] Failed to preload events")

        # 2️⃣ Потом слушаем живую очередь
        q = get_event_queue()

        while True:
            try:
                tx = q.get(timeout=10)
                logger.info(f"[SSE] Sending live event {tx.get('txid')}")
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

def start_mempool_worker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(mempool_ws_worker())
    except Exception:
        logger.exception("Mempool worker crashed")


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


if __name__ == "__main__":
    ensure_db()

    threading.Thread(target=clustering_loop, daemon=True).start()
    threading.Thread(target=start_mempool_worker, daemon=True).start()
    threading.Thread(target=price_sampler, daemon=True).start()
    threading.Thread(target=exchange_flow_sampler, daemon=True).start()
    threading.Thread(target=trainer, daemon=True).start()

    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=Config.DEBUG, threaded=True)