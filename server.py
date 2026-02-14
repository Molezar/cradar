from flask import Flask, jsonify, send_from_directory, Response
from flask_cors import CORS
import os
import threading
import asyncio
import json
import time
import requests
from config import Config
from database.database import get_db, init_db
from onchain import mempool_ws_handler, get_event_queue
from logger import get_logger

logger = get_logger(__name__)

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MINIAPP_DIR = os.path.join(BASE_DIR, "miniapp")

WINDOWS = [600, 3600]  # 10 min, 60 min


# ------------------ Binance price ------------------

def fetch_btc_price():
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=10)
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
                db.execute("INSERT OR IGNORE INTO btc_price(ts, price) VALUES (?,?)", (int(time.time()), price))
                db.commit()
                db.close()
                logger.debug(f"Sampled BTC price: {price}")
        except Exception as e:
            logger.exception(f"Error in price_sampler: {e}")
        time.sleep(30)


# ------------------ Whale flow sampler ------------------

def whale_flow_sampler():
    while True:
        try:
            now = int(time.time())
            since = now - 600

            db = get_db()
            r = db.execute("SELECT SUM(btc) as total FROM whale_tx WHERE time > ?", (since,)).fetchone()
            total = r["total"] or 0

            db.execute("INSERT OR REPLACE INTO whale_flow(ts, total_btc) VALUES (?,?)", (now, total))
            db.commit()
            db.close()

            logger.debug(f"Whale flow updated: {total} BTC in last 10 min")
        except Exception as e:
            logger.exception(f"Error in whale_flow_sampler: {e}")
        time.sleep(60)


# ------------------ Trainer ------------------

def trainer():
    while True:
        try:
            db = get_db()

            for w in WINDOWS:
                now = int(time.time())
                p1 = db.execute("SELECT price FROM btc_price WHERE ts < ? ORDER BY ts DESC LIMIT 1", (now,)).fetchone()
                p0 = db.execute("SELECT price FROM btc_price WHERE ts < ? ORDER BY ts DESC LIMIT 1", (now - w,)).fetchone()

                if not p0 or not p1:
                    continue

                dp = (p1["price"] - p0["price"]) / p0["price"]
                flow = db.execute("SELECT SUM(total_btc) as s FROM whale_flow WHERE ts > ?", (now - w,)).fetchone()["s"] or 0

                row = db.execute("SELECT weight, samples FROM whale_correlation WHERE window=?", (w,)).fetchone()

                if row:
                    weight = row["weight"]
                    samples = row["samples"]
                    new_weight = (weight * samples + dp / (flow + 1)) / (samples + 1)
                    db.execute("UPDATE whale_correlation SET weight=?, samples=? WHERE window=?", (new_weight, samples + 1, w))
                else:
                    new_weight = dp / (flow + 1)
                    db.execute("INSERT INTO whale_correlation VALUES (?,?,1)", (w, new_weight))

                logger.debug(f"Trainer updated window {w}: dp={dp:.6f}, flow={flow}, new weight={new_weight:.6f}")

            db.commit()
            db.close()
        except Exception as e:
            logger.exception(f"Error in trainer: {e}")

        time.sleep(300)


# ------------------ API ------------------

@app.route("/whales")
def whales():
    try:
        db = get_db()
        rows = db.execute("SELECT txid, btc, time FROM whale_tx ORDER BY time DESC LIMIT 50").fetchall()
        db.close()
        return jsonify({"count": len(rows), "whales": [dict(r) for r in rows]})
    except Exception as e:
        logger.exception(f"Error in /whales endpoint: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/price")
def price():
    try:
        db = get_db()
        r = db.execute("SELECT price FROM btc_price ORDER BY ts DESC LIMIT 1").fetchone()
        db.close()
        return jsonify({"price": r["price"] if r else None})
    except Exception as e:
        logger.exception(f"Error in /price endpoint: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/prediction")
def prediction():
    try:
        db = get_db()
        price_row = db.execute("SELECT price FROM btc_price ORDER BY ts DESC LIMIT 1").fetchone()
        if not price_row:
            return jsonify({})

        price = price_row["price"]
        out = {}

        for w in WINDOWS:
            r = db.execute("SELECT weight FROM whale_correlation WHERE window=?", (w,)).fetchone()
            if not r:
                continue

            pct = r["weight"] * 100
            out[str(w)] = {
                "pct": round(pct, 2),
                "target": round(price * (1 + pct / 100), 2)
            }

        db.close()
        return jsonify(out)
    except Exception as e:
        logger.exception(f"Error in /prediction endpoint: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/events")
def events():
    def stream():
        q = get_event_queue()
        while True:
            tx = q.get()
            yield f"data: {json.dumps(tx)}\n\n"
    return Response(stream(), mimetype="text/event-stream")


@app.route("/")
def index():
    return send_from_directory(MINIAPP_DIR, "index.html")


@app.route("/<path:path>")
def files(path):
    return send_from_directory(MINIAPP_DIR, path)


# ------------------ Startup ------------------

def start_ws():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(mempool_ws_handler())


if __name__ == "__main__":
    db_path = Config.DB_PATH
    db_path.parent.mkdir(exist_ok=True, parents=True)
    if not db_path.exists():
        logger.info(f"Database not found at {db_path}, initializing new one")
        init_db()

    threading.Thread(target=start_ws, daemon=True).start()
    threading.Thread(target=price_sampler, daemon=True).start()
    threading.Thread(target=whale_flow_sampler, daemon=True).start()
    threading.Thread(target=trainer, daemon=True).start()

    logger.info("Starting Flask server on 0.0.0.0:8000")
    app.run("0.0.0.0", 8000)