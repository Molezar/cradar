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
    """
    Показывает притоки и оттоки BTC на биржи за последний час
    + signal (ratio * volatility)
    + DELTA усиление
    + cluster concentration
    + динамические пороги (p90)
    """

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
        inflow, outflow, internal = row["inflow"] or 0, row["outflow"] or 0, row["internal"] or 0
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
        volatility = (vol_row["max_p"] - vol_row["min_p"]) / vol_row["min_p"] if vol_row and vol_row["max_p"] and vol_row["min_p"] else 0

        # --------------------------
        # historical signals for thresholds
        # --------------------------
        hist_rows = cursor.execute("""
            SELECT exchange_net_ratio, volatility
            FROM research_market
            WHERE exchange_net_ratio IS NOT NULL AND volatility IS NOT NULL
        """).fetchall()
        signals = [(r["exchange_net_ratio"] or 0)*(r["volatility"] or 0) for r in hist_rows]
        threshold = sorted(abs(s) for s in signals)[int(len(signals)*0.9)] if len(signals) >= 20 else 0.0005

        delta_values = [abs((hist_rows[i]["exchange_net_ratio"] or 0) - (hist_rows[i-1]["exchange_net_ratio"] or 0))
                        for i in range(1, len(hist_rows))]
        p95_delta = sorted(delta_values)[int(len(delta_values)*0.95)] if delta_values else 0.01

        prev_ratio = hist_rows[-1]["exchange_net_ratio"] if hist_rows else 0
        exchange_delta = exchange_ratio - prev_ratio

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
        max_cluster = max(r["cluster_btc"] or 0 for r in cluster_rows) if cluster_rows else 0
        cluster_concentration = (max_cluster / total_btc) if total_btc > 0 else 0

        # --------------------------
        # signal
        # --------------------------
        signal = exchange_ratio * volatility
        delta_note = ""
        if abs(exchange_delta) > p95_delta:
            signal *= 1.5
            delta_note = f"⚡ DELTA surge! ({exchange_delta:.4f} > {p95_delta:.4f}) → signal x1.5"

        # --------------------------
        # BTC price change
        # --------------------------
        cursor.execute("SELECT price FROM btc_price WHERE ts >= ? ORDER BY ts ASC LIMIT 1", (hour_ago,))
        start_row = cursor.fetchone()
        cursor.execute("SELECT price FROM btc_price ORDER BY ts DESC LIMIT 1")
        end_row = cursor.fetchone()
        conn.close()

        price_change = (end_row["price"] - start_row["price"]) / start_row["price"] * 100 if start_row and end_row and start_row["price"] else None

        # --------------------------
        # text
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
        )
        if abs(signal) < threshold:
            text += "⚪ signal below threshold → ignore (noise)\n\n"
        else:
            text += "🔴 SELL pressure (strong)\n\n" if signal > 0 else "🟢 BUY / accumulation (strong)\n\n"

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