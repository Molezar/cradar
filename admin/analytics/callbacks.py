# admin/analytics/callbacks.py
import os
import time
from config import Config
from logger import get_logger
from admin.keyboards import get_admin_to_main_bt
from .keyboards import get_analytics_kb
from database.database import get_db

logger = get_logger(__name__)

async def handle_exchange_flow_1h(callback):
    try:
        conn = get_db()
        cursor = conn.cursor()
        now = int(time.time())
        hour_ago = now - 3600

        # --------------------------
        # FLOWS
        # --------------------------
        cursor.execute("""
            SELECT SUM(CASE WHEN flow_type='DEPOSIT' THEN btc ELSE 0 END) as inflow,
                   SUM(CASE WHEN flow_type='WITHDRAW' THEN btc ELSE 0 END) as outflow,
                   SUM(CASE WHEN flow_type='INTERNAL' THEN btc ELSE 0 END) as internal
            FROM exchange_flow
            WHERE ts > ?
        """, (hour_ago,))
        row = cursor.fetchone()

        inflow = row["inflow"] or 0
        outflow = row["outflow"] or 0
        internal = row["internal"] or 0

        net = inflow - outflow
        total_flow = inflow + outflow
        exchange_ratio = net / total_flow if total_flow > 0 else 0

        # --------------------------
        # volatility
        # --------------------------
        cursor.execute("""
            SELECT MAX(price) as max_p, MIN(price) as min_p
            FROM btc_price
            WHERE ts > ?
        """, (hour_ago,))
        vol_row = cursor.fetchone()

        volatility = (
            (vol_row["max_p"] - vol_row["min_p"]) / vol_row["min_p"]
            if vol_row and vol_row["max_p"] and vol_row["min_p"]
            else 0
        )

        # --------------------------
        # historical
        # --------------------------
        hist_rows = cursor.execute("""
            SELECT exchange_net_ratio, volatility, price, price_1h
            FROM research_market
            WHERE exchange_net_ratio IS NOT NULL AND volatility IS NOT NULL
        """).fetchall()

        signal_hist = [
            (r["exchange_net_ratio"] or 0) * (r["volatility"] or 0)
            for r in hist_rows
        ]

        threshold = (
            sorted(abs(s) for s in signal_hist)[int(len(signal_hist) * 0.9)]
            if len(signal_hist) >= 20 else 0.0005
        )

        # --------------------------
        # DELTA
        # --------------------------
        prev_ratio = (hist_rows[-1]["exchange_net_ratio"] or 0) if hist_rows else 0
        exchange_delta = exchange_ratio - prev_ratio

        delta_values = [
            abs((hist_rows[i]["exchange_net_ratio"] or 0) -
                (hist_rows[i - 1]["exchange_net_ratio"] or 0))
            for i in range(1, len(hist_rows))
        ]

        p95_delta = (
            sorted(delta_values)[int(len(delta_values) * 0.95)]
            if delta_values else 0.01
        )

        # --------------------------
        # cluster concentration
        # --------------------------
        cluster_rows = cursor.execute("""
            SELECT cluster_id, SUM(btc) as cluster_btc
            FROM exchange_flow
            WHERE ts > ?
            GROUP BY cluster_id
        """, (hour_ago,)).fetchall()

        total_btc = sum(r["cluster_btc"] or 0 for r in cluster_rows)
        max_cluster = max((r["cluster_btc"] or 0 for r in cluster_rows), default=0)

        cluster_concentration = (max_cluster / total_btc) if total_btc > 0 else 0

        # --------------------------
        # SIGNAL
        # --------------------------
        signal = exchange_ratio * volatility
        delta_note = ""

        if abs(exchange_delta) > p95_delta:
            signal *= 1.5
            delta_note = f"⚡ DELTA surge! ({exchange_delta:.4f} > {p95_delta:.4f}) → signal x1.5"

        # --------------------------
        # PURE SIGNAL (NO HISTORY) ✅
        # --------------------------
        strength = (abs(signal) / threshold) if threshold > 0 else 0
        strength = min(strength, 1.0)

        confidence = 50 + 40 * strength * (1 + cluster_concentration) / 2

        if strength < 0.1:
            pure_text = (
                "🧠 Pure signal (no history):\n"
                "⚪ NEUTRAL (very weak signal)\n\n"
            )
        else:
            if signal < 0:
                pure_text = (
                    "🧠 Pure signal (no history):\n"
                    f"🟢 BUY confidence: {confidence:.1f}%\n\n"
                )
            else:
                pure_text = (
                    "🧠 Pure signal (no history):\n"
                    f"🔴 SELL confidence: {confidence:.1f}%\n\n"
                )

        # --------------------------
        # HISTORICAL PROBABILITY
        # --------------------------
        def safe_delta(r):
            if r["price"] is None or r["price_1h"] is None or r["price"] == 0:
                return None
            return (r["price_1h"] - r["price"]) / r["price"]

        weighted_up = 0.0
        weighted_down = 0.0
        total_weight = 0.0

        for r in hist_rows:
            hist_signal = (r["exchange_net_ratio"] or 0) * (r["volatility"] or 0)

            if abs(hist_signal) < threshold:
                continue

            d = safe_delta(r)
            if d is None:
                continue

            weight = abs(hist_signal) / threshold
            total_weight += weight

            if hist_signal > 0 and d < 0:
                weighted_down += weight
            elif hist_signal < 0 and d > 0:
                weighted_up += weight

        alpha = 1.0
        beta = 1.0

        p_up = ((weighted_up + alpha) / (total_weight + alpha + beta) * 100) if total_weight else 50
        p_down = ((weighted_down + alpha) / (total_weight + alpha + beta) * 100) if total_weight else 50

        # --------------------------
        # SIGNAL-BASED PROBABILITY
        # --------------------------
        if signal < 0:
            p_signal_up = confidence
            p_signal_down = 100 - confidence
        else:
            p_signal_down = confidence
            p_signal_up = 100 - confidence

        # --------------------------
        # FINAL COMBINED PROBABILITY
        # --------------------------
        final_p_up = (p_up * 0.6) + (p_signal_up * 0.4)
        final_p_down = (p_down * 0.6) + (p_signal_down * 0.4)

        # --------------------------
        # BTC price change
        # --------------------------
        cursor.execute("""
            SELECT price FROM btc_price 
            WHERE ts >= ? ORDER BY ts ASC LIMIT 1
        """, (hour_ago,))
        start_row = cursor.fetchone()

        cursor.execute("""
            SELECT price FROM btc_price 
            ORDER BY ts DESC LIMIT 1
        """)
        end_row = cursor.fetchone()

        conn.close()

        price_change = (
            (end_row["price"] - start_row["price"]) / start_row["price"] * 100
            if start_row and end_row and start_row["price"] else None
        )

        # --------------------------
        # TEXT
        # --------------------------
        text = (
            "📈 Exchange flow (last 1h)\n\n"
            f"⬇️ inflow: {inflow:.2f} BTC\n"
            f"⬆️ outflow: {outflow:.2f} BTC\n"
            f"🔁 internal: {internal:.2f} BTC\n\n"
            f"📊 net flow: {net:.2f} BTC\n"
            f"📐 ratio: {exchange_ratio:.4f}\n"
            f"🌊 volatility: {volatility:.4f}\n"
            f"🔥 signal: {signal:.6f}\n"
            f"⚙️ threshold (p90): {threshold:.6f}\n"
            f"💠 cluster concentration: {cluster_concentration:.3f}\n\n"
            f"{pure_text}"
            f"🎯 Probabilities (combined):\n"
            f"🟢 BUY success: {final_p_up:.1f}%\n"
            f"🔴 SELL success: {final_p_down:.1f}%\n\n"
        )

        if abs(signal) < threshold:
            text += "⚪ signal below threshold → weak signal (but bias shown above)\n\n"
        else:
            if signal > 0:
                text += "🔴 SELL pressure\n\n"
            else:
                text += "🟢 BUY / accumulation\n\n"

        if delta_note:
            text += f"{delta_note}\n\n"

        if price_change is not None:
            text += f"💰 BTC price change: {price_change:.2f}%\n"

        await callback.message.edit_text(
            text,
            reply_markup=get_analytics_kb(),
            parse_mode=None
        )

    except Exception as e:
        logger.exception(e)
        await callback.message.edit_text(
            "❌ Ошибка получения exchange flow",
            reply_markup=get_admin_to_main_bt()
        )

async def handle_whale_pressure_15m(callback):
    """
    Анализ давления китов за 15 минут
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                ef.flow_type,
                SUM(ef.btc) as total_btc
            FROM exchange_flow ef
            JOIN clusters c
                ON ef.cluster_id = c.id
            WHERE ef.ts > CAST(strftime('%s','now') AS INTEGER) - 900
            AND c.cluster_type = 'EXCHANGE'
            GROUP BY ef.flow_type
        """)

        rows = cursor.fetchall()
        conn.close()

        inflow = 0
        outflow = 0

        for r in rows:
            if r["flow_type"] == "DEPOSIT":
                inflow += r["total_btc"] or 0
            elif r["flow_type"] == "WITHDRAW":
                outflow += r["total_btc"] or 0

        net = inflow - outflow

        # -----------------------------------------
        # text formatting
        # -----------------------------------------

        text = (
            "🧠 Whale pressure (15m)\n\n"
            f"⬇️ whale → exchange: {inflow:.2f} BTC\n"
            f"⬆️ exchange → whale: {outflow:.2f} BTC\n\n"
            f"📊 net: {net:.2f} BTC\n"
        )

        # шум / мало активности
        if abs(net) < 20:
            text += "🟡 net < ~20 BTC → шум / мало активности\n\n"
        else:
            text += "\n"

        # -----------------------------------------
        # market interpretation
        # -----------------------------------------

        if net > 100:
            text += "🔴 🔥 сильное давление продаж (BTC поступает на биржи)"
        elif net > 20:
            text += "🟠 ⚠️ умеренное давление продаж"
        elif net < -100:
            text += "🟢 🚀 сильное давление покупок (BTC выводится с бирж)"
        elif net < -20:
            text += "🟢 📈 умеренное давление покупок"
        else:
            text += "🟡 ➖ нейтральное давление"

        await callback.message.edit_text(
            text,
            reply_markup=get_analytics_kb(),
            parse_mode=None  # <<< фикс для ошибки Telegram
        )

    except Exception as e:
        logger.exception(e)
        await callback.message.edit_text(
            "❌ Ошибка анализа whale pressure",
            reply_markup=get_admin_to_main_bt(),
            parse_mode=None
        )