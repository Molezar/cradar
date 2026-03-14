# admin/analytics/callbacks.py
import os
import time
from aiogram.types import FSInputFile
from config import Config
from logger import get_logger
from admin.keyboards import get_admin_to_main_bt
from .keyboards import get_analytics_kb
from database.database import get_db

logger = get_logger(__name__)


async def handle_tables_info(callback):
    """
    Показывает количество записей в каждой таблице БД
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type='table'
            AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """)

        tables = [row[0] for row in cursor.fetchall()]

        lines = []

        for table in tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                lines.append(f"{table}: {count}")
            except Exception:
                lines.append(f"{table}: error")

        conn.close()

        text = "📊 Таблицы БД:\n\n" + "\n".join(lines)

        if len(text) > 3500:
            text = text[:3500] + "\n..."

        await callback.message.edit_text(
            text,
            reply_markup=get_analytics_kb()
        )

    except Exception as e:
        logger.exception(e)
        await callback.message.edit_text(
            "❌ Ошибка получения информации о таблицах",
            reply_markup=get_admin_to_main_bt()
        )

async def handle_cluster_health(callback):
    """
    Показывает метрику здоровья кластеризации (последние 2 часа)
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*)
            FROM whale_classification
            WHERE time > strftime('%s','now') - 7200
        """)
        total = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM whale_classification
            WHERE (from_cluster IS NOT NULL
               OR to_cluster IS NOT NULL)
            AND time > strftime('%s','now') - 7200
        """)
        clustered = cursor.fetchone()[0]

        conn.close()

        ratio = 0
        if total > 0:
            ratio = clustered / total

        text = (
            "🧠 Cluster health (last 2h)\n\n"
            f"total flows: {total}\n"
            f"clustered flows: {clustered}\n\n"
            f"cluster ratio: {ratio:.3f}\n\n"
        )

        if ratio > 0.35:
            text += "✅ кластеризация работает нормально"
        elif ratio > 0.15:
            text += "⚠️ кластеризация слабая"
        else:
            text += "❌ биржи почти не детектятся"

        await callback.message.edit_text(
            text,
            reply_markup=get_analytics_kb()
        )

    except Exception as e:
        logger.exception(e)
        await callback.message.edit_text(
            "❌ Ошибка получения cluster health",
            reply_markup=get_admin_to_main_bt()
        )

async def handle_top_clusters(callback):
    """
    Показывает крупнейшие кластеры
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, cluster_type, size, confidence
            FROM clusters
            ORDER BY size DESC
            LIMIT 10
        """)

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            text = "📊 Кластеры не найдены"
        else:
            lines = []
            for r in rows:
                lines.append(
                    f"id:{r['id']} | {r['cluster_type']} | "
                    f"size:{r['size']} | conf:{r['confidence']:.2f}"
                )

            text = "📊 Top clusters\n\n" + "\n".join(lines)

        await callback.message.edit_text(
            text,
            reply_markup=get_analytics_kb()
        )

    except Exception as e:
        logger.exception(e)
        await callback.message.edit_text(
            "❌ Ошибка получения кластеров",
            reply_markup=get_admin_to_main_bt()
        )

async def handle_exchange_flow_1h(callback):
    """
    Показывает притоки и оттоки BTC на биржи за последний час
    + internal flows
    + изменение цены BTC
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        now = int(time.time())
        hour_ago = now - 3600

        # flows
        cursor.execute("""
            SELECT
                SUM(CASE WHEN flow_type = 'DEPOSIT' THEN btc ELSE 0 END) as inflow,
                SUM(CASE WHEN flow_type = 'WITHDRAW' THEN btc ELSE 0 END) as outflow,
                SUM(CASE WHEN flow_type = 'INTERNAL' THEN btc ELSE 0 END) as internal
            FROM exchange_flow
            WHERE ts > ?
        """, (hour_ago,))

        row = cursor.fetchone()
        conn.close()

        inflow = row["inflow"] or 0
        outflow = row["outflow"] or 0
        internal = row["internal"] or 0
        net = inflow - outflow

        # -----------------------------------------
        # BTC price change
        # -----------------------------------------
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT price
            FROM btc_price
            WHERE ts >= ?
            ORDER BY ts ASC
            LIMIT 1
        """, (hour_ago,))
        start_row = cursor.fetchone()

        cursor.execute("""
            SELECT price
            FROM btc_price
            ORDER BY ts DESC
            LIMIT 1
        """)
        end_row = cursor.fetchone()
        conn.close()

        price_change = None
        if start_row and end_row:
            start_price = start_row["price"]
            end_price = end_row["price"]
            if start_price:
                price_change = (end_price - start_price) / start_price * 100

        # -----------------------------------------
        # text
        # -----------------------------------------
        text = (
            "📈 Exchange flow (last 1h)\n\n"
            f"⬇️ inflow: {inflow:.2f} BTC\n"
            f"⬆️ outflow: {outflow:.2f} BTC\n"
            f"🔁 internal: {internal:.2f} BTC\n\n"
            f"📊 net flow: {net:.2f} BTC\n"
        )

        # инфо-блок про шум
        if abs(net) < 500:
            text += "🟡 net < ~500 BTC за час = шум\n\n"

        if price_change is not None:
            text += f"💰 BTC price change: {price_change:.2f}%\n\n"

        # market interpretation
        if net > 0:
            text += "🔴 sell pressure (BTC поступает на биржи)"
        elif net < 0:
            text += "🟢 accumulation (BTC выводится с бирж)"
        else:
            text += "🟡 neutral flow"

        await callback.message.edit_text(
            text,
            reply_markup=get_analytics_kb(),
            parse_mode=None  # <<< важно!
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

async def handle_flow_pipeline_check(callback):
    """
    Проверка pipeline:
    exchange detection → cluster assignment → flow recording
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        # типы потоков
        cursor.execute("""
            SELECT flow_type, COUNT(*) as cnt
            FROM exchange_flow
            GROUP BY flow_type
        """)
        rows = cursor.fetchall()

        flow_lines = []
        for r in rows:
            flow_lines.append(f"{r['flow_type']}: {r['cnt']}")

        # сколько кластеров участвует
        cursor.execute("""
            SELECT COUNT(DISTINCT cluster_id) as clusters
            FROM exchange_flow
        """)
        clusters = cursor.fetchone()["clusters"]

        # топ кластеров по объёму
        cursor.execute("""
            SELECT cluster_id, SUM(btc) as total
            FROM exchange_flow
            GROUP BY cluster_id
            ORDER BY total DESC
            LIMIT 5
        """)
        top = cursor.fetchall()

        conn.close()

        text = "🔬 Flow pipeline check\n\n"

        if flow_lines:
            text += "flows:\n"
            text += "\n".join(flow_lines) + "\n\n"
        else:
            text += "flows: 0\n\n"

        text += f"clusters in flows: {clusters}\n\n"

        if top:
            text += "top clusters by volume:\n"
            for r in top:
                text += f"id {r['cluster_id']} : {r['total']:.2f} BTC\n"
            text += "\n"

        if clusters > 5:
            text += "✅ pipeline выглядит нормально"
        elif clusters > 1:
            text += "⚠️ мало кластеров"
        else:
            text += "❌ кластеры почти не участвуют"

        await callback.message.edit_text(
            text,
            reply_markup=get_analytics_kb()
        )

    except Exception as e:
        logger.exception(e)
        await callback.message.edit_text(
            "❌ Ошибка проверки pipeline",
            reply_markup=get_admin_to_main_bt()
        )