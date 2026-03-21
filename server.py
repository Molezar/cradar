#server.py
from flask import Flask, jsonify, send_from_directory, request, Response
from flask_cors import CORS
import os
import threading
import asyncio
import json
import time
import requests
import queue

from config import Config
from database.database import get_db, init_db
from onchain import mempool_ws_worker, get_event_queue, behavioral_to_exchange
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

def fetch_btc_price_with_fallback():
    """Получает цену из нескольких источников с резервированием"""
    sources = [
        {
            "name": "Binance",
            "url": "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
            "parser": lambda x: float(x["price"])
        },
        {
            "name": "Bybit",
            "url": "https://api.bybit.com/v5/market/tickers?category=spot&symbol=BTCUSDT",
            "parser": lambda x: float(x["result"]["list"][0]["lastPrice"])
        },
        {
            "name": "KuCoin",
            "url": "https://api.kucoin.com/api/v1/market/orderbook/level1?symbol=BTC-USDT",
            "parser": lambda x: float(x["data"]["price"])
        },
        {
            "name": "OKX",
            "url": "https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT",
            "parser": lambda x: float(x["data"][0]["last"])
        }
    ]
    
    for source in sources:
        try:
            r = requests.get(source["url"], timeout=5)
            r.raise_for_status()
            price = source["parser"](r.json())
            if price and price > 0:
                logger.info(f"Price from {source['name']}: {price}")
                return price
        except Exception as e:
            logger.warning(f"Failed to fetch from {source['name']}: {e}")
            continue
    
    # Если все источники недоступны, пробуем получить последнюю цену из БД
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT price FROM btc_price ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        if row and row["price"] > 0:
            logger.warning(f"Using last known price from DB: {row['price']}")
            return row["price"]
    except Exception as e:
        logger.error(f"Failed to get price from DB: {e}")
    finally:
        if conn:
            conn.close()
    
    return None

def price_sampler():
    """Обновляет цену в БД каждые 30 секунд с резервными источниками"""
    consecutive_failures = 0
    
    while True:
        try:
            # Пробуем получить цену с резервированием
            price = fetch_btc_price_with_fallback()
            
            if price:
                consecutive_failures = 0
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
                    logger.info(f"✅ Price updated in DB: {price}")
                    
                except Exception as db_error:
                    logger.error(f"Database error in price_sampler: {db_error}")
                finally:
                    if conn:
                        conn.close()
            else:
                consecutive_failures += 1
                logger.error(f"❌ Failed to fetch price from all sources (failure #{consecutive_failures})")
                
                # Если много ошибок подряд, увеличиваем паузу
                if consecutive_failures > 5:
                    logger.warning("Too many failures, increasing sleep time")
                    time.sleep(60)
                    continue
                    
        except Exception as e:
            logger.exception(f"Critical error in price_sampler: {e}")
            consecutive_failures += 1
        
        # Обычная пауза 30 секунд
        time.sleep(30)

def fetch_binance_klines(limit=2):
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={
                "symbol": "BTCUSDT",
                "interval": "1m",
                "limit": limit
            },
            timeout=10
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"Failed to fetch klines: {e}")
        return []

def candle_sampler():
    while True:
        try:
            klines = fetch_binance_klines(limit=2)

            if not klines:
                time.sleep(30)
                continue

            conn = None
            try:
                conn = get_db()
                c = conn.cursor()

                for k in klines:
                    open_time = int(k[0] / 1000)

                    c.execute("""
                        INSERT INTO btc_candles_1m
                        (open_time, open, high, low, close, volume)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(open_time) DO UPDATE SET
                            open=excluded.open,
                            high=excluded.high,
                            low=excluded.low,
                            close=excluded.close,
                            volume=excluded.volume
                    """, (
                        open_time,
                        float(k[1]),
                        float(k[2]),
                        float(k[3]),
                        float(k[4]),
                        float(k[5])
                    ))

                conn.commit()

            finally:
                if conn:
                    conn.close()

        except Exception:
            logger.exception("Candle sampler error")

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
        
async def research_market_sampler():
    """
    Сохраняет состояние рынка для последующего анализа корреляции
    + кластерная концентрация (max / total)
    """

    while True:
        try:
            now = int(time.time())
            conn = None
            try:
                conn = get_db()
                c = conn.cursor()

                # ---------------------------------
                # whale pressure (15m)
                # ---------------------------------
                whale_since = now - 900
                rows = c.execute("""
                    SELECT
                        ef.flow_type,
                        SUM(ef.btc) as total_btc
                    FROM exchange_flow ef
                    JOIN clusters c ON ef.cluster_id = c.id
                    WHERE ef.ts > ? AND c.cluster_type = 'EXCHANGE'
                    GROUP BY ef.flow_type
                """, (whale_since,)).fetchall()

                inflow = outflow = 0
                for r in rows:
                    if r["flow_type"] == "DEPOSIT":
                        inflow += r["total_btc"] or 0
                    elif r["flow_type"] == "WITHDRAW":
                        outflow += r["total_btc"] or 0
                whale_net = inflow - outflow

                # ---------------------------------
                # exchange flow (1h)
                # ---------------------------------
                hour_since = now - 3600
                row = c.execute("""
                    SELECT
                        SUM(CASE WHEN flow_type = 'DEPOSIT' THEN btc ELSE 0 END) as inflow,
                        SUM(CASE WHEN flow_type = 'WITHDRAW' THEN btc ELSE 0 END) as outflow
                    FROM exchange_flow
                    WHERE ts > ?
                """, (hour_since,)).fetchone()

                inflow = row["inflow"] or 0
                outflow = row["outflow"] or 0
                exchange_net = inflow - outflow

                total_flow = inflow + outflow
                exchange_net_ratio = exchange_net / total_flow if total_flow > 0 else 0

                # ---------------------------------
                # volatility (1h)
                # ---------------------------------
                vol_row = c.execute("""
                    SELECT MAX(price) as max_p, MIN(price) as min_p
                    FROM btc_price
                    WHERE ts > ?
                """, (hour_since,)).fetchone()
                volatility = (vol_row["max_p"] - vol_row["min_p"]) / vol_row["min_p"] if vol_row and vol_row["max_p"] and vol_row["min_p"] else 0

                # ---------------------------------
                # cluster concentration
                # ---------------------------------
                cluster_rows = c.execute("""
                    SELECT cluster_id, SUM(btc) as cluster_btc
                    FROM exchange_flow
                    WHERE ts > ?
                    GROUP BY cluster_id
                """, (hour_since,)).fetchall()

                total_btc = sum(r["cluster_btc"] or 0 for r in cluster_rows)
                max_cluster = max(r["cluster_btc"] or 0 for r in cluster_rows) if cluster_rows else 0
                cluster_concentration = (max_cluster / total_btc) if total_btc > 0 else 0

                # ---------------------------------
                # current price
                # ---------------------------------
                price_row = c.execute("SELECT price FROM btc_price ORDER BY ts DESC LIMIT 1").fetchone()
                if not price_row:
                    continue
                price = price_row["price"]

                # ---------------------------------
                # insert research row
                # ---------------------------------
                c.execute("""
                    INSERT INTO research_market (
                        ts, whale_net, exchange_net, exchange_net_ratio,
                        price, volatility, cluster_concentration
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    now, whale_net, exchange_net, exchange_net_ratio,
                    price, volatility, cluster_concentration
                ))

                conn.commit()

            finally:
                if conn:
                    conn.close()

        except Exception:
            logger.exception("research_market_sampler error")

        await asyncio.sleep(300)

async def research_market_updater():
    """
    Обновляет price_15m и price_1h когда проходит время
    """

    while True:
        try:
            now = int(time.time())

            conn = None
            try:
                conn = get_db()
                c = conn.cursor()

                price_row = c.execute("""
                    SELECT price
                    FROM btc_price
                    ORDER BY ts DESC
                    LIMIT 1
                """).fetchone()

                if not price_row:
                    continue

                price = price_row["price"]

                # update 15m
                c.execute("""
                    UPDATE research_market
                    SET price_15m = ?
                    WHERE price_15m IS NULL
                      AND ts <= ?
                """, (price, now - 900))

                # update 1h
                c.execute("""
                    UPDATE research_market
                    SET price_1h = ?
                    WHERE price_1h IS NULL
                      AND ts <= ?
                """, (price, now - 3600))

                conn.commit()

            finally:
                if conn:
                    conn.close()

        except Exception:
            logger.exception("research_market_updater error")

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


# =============================================
# BEHAVIORAL → EXCHANGE UPGRADE WORKER
# =============================================

async def behavioral_upgrade_worker():

    while True:
        try:
            now = int(time.time())

            conn = None
            try:
                conn = get_db()
                c = conn.cursor()

                rows = c.execute("""
                    SELECT id
                    FROM clusters
                    WHERE cluster_type='BEHAVIORAL'
                """).fetchall()

                upgraded = 0

                for r in rows:
                    cid = r["id"]

                    if behavioral_to_exchange(cid, c, now):
                        upgraded += 1

                if upgraded:
                    logger.info(f"[CLUSTER] Upgraded {upgraded} behavioral clusters")

                conn.commit()

            finally:
                if conn:
                    conn.close()

        except Exception:
            logger.exception("Behavioral upgrade worker error")

        await asyncio.sleep(300)  # каждые 5 минут


# =============================================
# SIGNAL WORKERS
# =============================================

async def signal_alert_worker():
    """
    Генерирует сигнал (опережающий)
    """
    while True:
        try:
            now = int(time.time())
            hour_ago = now - 3600

            conn = get_db()
            c = conn.cursor()

            # ---- FLOW ----
            row = c.execute("""
                SELECT 
                    SUM(CASE WHEN flow_type='DEPOSIT' THEN btc ELSE 0 END) as inflow,
                    SUM(CASE WHEN flow_type='WITHDRAW' THEN btc ELSE 0 END) as outflow
                FROM exchange_flow
                WHERE ts > ?
            """, (hour_ago,)).fetchone()

            inflow = row["inflow"] or 0
            outflow = row["outflow"] or 0

            net = inflow - outflow
            total = inflow + outflow
            ratio = net / total if total > 0 else 0

            # ---- VOL ----
            vol_row = c.execute("""
                SELECT MAX(price) as max_p, MIN(price) as min_p
                FROM btc_price
                WHERE ts > ?
            """, (hour_ago,)).fetchone()

            volatility = (vol_row["max_p"] - vol_row["min_p"]) / vol_row["min_p"] if vol_row else 0

            signal = ratio * volatility

            # ---- threshold ----
            hist = c.execute("""
                SELECT exchange_net_ratio, volatility
                FROM research_market
            """).fetchall()

            signals = [(r["exchange_net_ratio"] or 0)*(r["volatility"] or 0) for r in hist]

            if len(signals) < 50:
                await asyncio.sleep(60)
                continue

            threshold = sorted(abs(s) for s in signals)[int(len(signals)*0.95)]

            # ---- SIGNAL ----
            if abs(signal) > threshold:

                direction = "SELL" if signal > 0 else "BUY"

                c.execute("""
                    INSERT INTO signal_events (ts, direction, signal, threshold, status)
                    VALUES (?, ?, ?, ?, 'WAITING')
                """, (now, direction, signal, threshold))

                conn.commit()

                logger.info(f"🚨 SIGNAL: {direction} | {signal:.6f}")

            conn.close()

        except Exception:
            logger.exception("signal_alert_worker error")

        await asyncio.sleep(60)
        
async def entry_alert_worker():
    """
    Ждёт подтверждение цены
    """
    while True:
        try:
            now = int(time.time())

            conn = get_db()
            c = conn.cursor()

            # берём незакрытые сигналы
            rows = c.execute("""
                SELECT * FROM signal_events
                WHERE status='WAITING'
                AND ts > ?
            """, (now - 3600,)).fetchall()

            if not rows:
                conn.close()
                await asyncio.sleep(30)
                continue

            # текущая цена
            price_row = c.execute("""
                SELECT price FROM btc_price
                ORDER BY ts DESC LIMIT 1
            """).fetchone()

            if not price_row:
                conn.close()
                await asyncio.sleep(30)
                continue

            current_price = price_row["price"]

            for r in rows:
                signal_id = r["id"]
                direction = r["direction"]
                signal_ts = r["ts"]

                # цена в момент сигнала
                start_row = c.execute("""
                    SELECT price FROM btc_price
                    WHERE ts >= ?
                    ORDER BY ts ASC LIMIT 1
                """, (signal_ts,)).fetchone()

                if not start_row:
                    continue

                start_price = start_row["price"]

                delta = (current_price - start_price) / start_price

                # ---- УСЛОВИЕ ВХОДА ----
                if direction == "SELL" and delta < -0.001:
                    trigger = True
                elif direction == "BUY" and delta > 0.001:
                    trigger = True
                else:
                    trigger = False

                if trigger:
                    c.execute("""
                        UPDATE signal_events
                        SET status='TRIGGERED', triggered_ts=?
                        WHERE id=?
                    """, (now, signal_id))

                    conn.commit()

                    logger.info(f"✅ ENTRY: {direction} | delta={delta:.4f}")

            conn.close()

        except Exception:
            logger.exception("entry_alert_worker error")

        await asyncio.sleep(30)
        

# =============================================
# API
# =============================================

@app.route("/alerts/signals")
def get_signals():
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM signal_events
        ORDER BY ts DESC LIMIT 50
    """).fetchall()
    conn.close()

    return jsonify([dict(r) for r in rows])
    
@app.route("/alerts/entries")
def get_entries():
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM signal_events
        WHERE status='TRIGGERED'
        ORDER BY triggered_ts DESC LIMIT 50
    """).fetchall()
    conn.close()

    return jsonify([dict(r) for r in rows])


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
                confidence,
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


@app.route("/marketpulse")
def marketpulse():
    """
    Возвращает:
    {
        trend: "UP"|"DOWN"|"NEUTRAL",
        confidence: float (0..1),
        keyFlows: [{cluster_id, btc, flow_type}]
    }
    """
    window = 600  # последние 10 минут
    now = int(time.time())
    since = now - window

    conn = None
    try:
        conn = get_db()
        # Берём net_flow по кластерам за последние 10 минут
        rows = conn.execute("""
            SELECT 
                cluster_id,
                SUM(CASE WHEN flow_type='DEPOSIT' THEN btc ELSE 0 END) -
                SUM(CASE WHEN flow_type='WITHDRAW' THEN btc ELSE 0 END) AS net_flow
            FROM exchange_flow
            WHERE ts > ?
            GROUP BY cluster_id
        """, (since,)).fetchall()

        total_net = sum(r["net_flow"] for r in rows)

        # Определяем тренд
        if total_net > 0.01:
            trend = "DOWN"  # вывод BTC с биржи
        elif total_net < -0.01:
            trend = "UP"    # приток BTC на биржу
        else:
            trend = "NEUTRAL"

        # Confidence = нормализуем к 0..1 по max abs net_flow
        max_abs = max((abs(r["net_flow"]) for r in rows), default=1)
        confidence = min(abs(total_net) / max_abs, 1.0)

        # KeyFlows: топ 5 кластеров по абсолютной величине net_flow
        top_flows = sorted(rows, key=lambda r: abs(r["net_flow"]), reverse=True)[:5]

        key_flows = []
        for r in top_flows:
            flow_type = "DEPOSIT" if r["net_flow"] < 0 else "WITHDRAW" if r["net_flow"] > 0 else "INTERNAL"
            key_flows.append({
                "cluster_id": r["cluster_id"],
                "btc": round(r["net_flow"], 2),
                "flow_type": flow_type
            })

        return jsonify({
            "trend": trend,
            "confidence": round(confidence, 2),
            "keyFlows": key_flows
        })

    except Exception:
        logger.exception("MarketPulse endpoint error")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        if conn:
            conn.close()


@app.route("/volumes")
def volumes():
    conn = None
    try:
        conn = get_db()
        c = conn.cursor()
        now = int(time.time())
        since = now - 3600  # последний час

        row = c.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN flow_type='DEPOSIT' THEN btc END), 0) as deposit,
                COALESCE(SUM(CASE WHEN flow_type='WITHDRAW' THEN btc END), 0) as withdraw
            FROM whale_classification
            WHERE time > ?
            AND flow_type IN ('DEPOSIT','WITHDRAW')
        """, (since,)).fetchone()

        deposit = row["deposit"]
        withdraw = row["withdraw"]
        net = withdraw - deposit

        return jsonify({
            "deposit": round(deposit, 2),
            "withdraw": round(withdraw, 2),
            "net": round(net, 2),
            "since": since,
            "now": now
        })

    except Exception:
        logger.exception("Volumes endpoint error")
        return jsonify({"error": "Internal server error"}), 500

    finally:
        if conn:
            conn.close()

            
@app.route("/exchange_flow")
def exchange_flow():
    """
    Возвращает net_flow по кластерам за последние N секунд.
    Параметр query: ?window=600 (по умолчанию 600 секунд = 10 минут)
    """
    window = int(request.args.get("window", 600))  # секунд
    now = int(time.time())
    since = now - window

    conn = None
    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT 
                cluster_id,
                SUM(CASE WHEN flow_type='DEPOSIT' THEN btc ELSE 0 END) AS deposit,
                SUM(CASE WHEN flow_type='WITHDRAW' THEN btc ELSE 0 END) AS withdraw,
                SUM(CASE WHEN flow_type='DEPOSIT' THEN btc ELSE 0 END) -
                SUM(CASE WHEN flow_type='WITHDRAW' THEN btc ELSE 0 END) AS net_flow
            FROM exchange_flow
            WHERE ts > ?
            GROUP BY cluster_id
            ORDER BY net_flow DESC
        """, (since,)).fetchall()

        result = [dict(r) for r in rows]
        return jsonify({
            "window": window,
            "count": len(result),
            "flows": result
        })

    except Exception:
        logger.exception("Exchange flow endpoint error")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        if conn:
            conn.close()


@app.route("/exchange_flow_raw")
def exchange_flow_raw():
    """
    Debug endpoint.
    Возвращает реальные записи из exchange_flow (DEPOSIT/WITHDRAW)
    чтобы проверить есть ли данные.

    Параметры:
        ?limit=100
    """

    limit = int(request.args.get("limit", 100))

    conn = None
    try:
        conn = get_db()

        rows = conn.execute("""
            SELECT
                ts,
                cluster_id,
                flow_type,
                btc
            FROM exchange_flow
            WHERE flow_type IN ('DEPOSIT', 'WITHDRAW')
            ORDER BY ts DESC
            LIMIT ?
        """, (limit,)).fetchall()

        result = [dict(r) for r in rows]

        return jsonify({
            "count": len(result),
            "rows": result
        })

    except Exception:
        logger.exception("Exchange flow raw endpoint error")
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


@app.route("/candles")
def candles():
    limit = int(request.args.get("limit", 100))

    conn = None
    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT open_time, open, high, low, close, volume
            FROM btc_candles_1m
            ORDER BY open_time DESC
            LIMIT ?
        """, (limit,)).fetchall()

        return jsonify([dict(r) for r in rows])

    except Exception:
        logger.exception("Candles endpoint error")
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
                SELECT
                    txid,
                    btc,
                    confidence,
                    time,
                    flow_type,
                    from_cluster,
                    to_cluster
                FROM whale_classification
                WHERE btc >= ?
                ORDER BY time DESC
                LIMIT 50
            """, (Config.ALERT_WHALE_BTC,)).fetchall()

            for r in reversed(rows):
                yield f"data: {json.dumps(dict(r))}\n\n"

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


# ==============================================
# STARTUP
# ==============================================

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


def start_async_tasks_loop():
    """Запускает все async задачи в одном лупе"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(exchange_flow_sampler())
    loop.create_task(research_market_sampler())
    loop.create_task(research_market_updater())
    loop.create_task(trainer())
    loop.create_task(mempool_ws_worker())
    loop.create_task(behavioral_upgrade_worker())
    loop.create_task(signal_alert_worker())
    loop.create_task(entry_alert_worker())
    loop.run_forever()


if __name__ == "__main__":
    ensure_db()

    # Синхронные воркеры
    threading.Thread(target=clustering_loop, daemon=True).start()
    threading.Thread(target=price_sampler, daemon=True).start()
    threading.Thread(target=candle_sampler, daemon=True).start()

    # Все async задачи в одном лупе
    threading.Thread(target=start_async_tasks_loop, daemon=True).start()

    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=Config.DEBUG, threaded=True)