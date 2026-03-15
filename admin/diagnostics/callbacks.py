# admin/diagnostics/callbacks.py
import os
import time
from aiogram.types import FSInputFile
from config import Config
from logger import get_logger
from admin.keyboards import get_admin_to_main_bt
from .keyboards import get_diagnostics_kb
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
            reply_markup=get_diagnostics_kb()
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
            reply_markup=get_diagnostics_kb()
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
            reply_markup=get_diagnostics_kb()
        )

    except Exception as e:
        logger.exception(e)
        await callback.message.edit_text(
            "❌ Ошибка получения кластеров",
            reply_markup=get_admin_to_main_bt()
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
            reply_markup=get_diagnostics_kb()
        )

    except Exception as e:
        logger.exception(e)
        await callback.message.edit_text(
            "❌ Ошибка проверки pipeline",
            reply_markup=get_admin_to_main_bt()
        )
        
async def handle_research_correlation(callback):
    """
    Строит корреляцию между:
    whale_net → price_15m
    exchange_net → price_1h
    """

    try:
        conn = get_db()
        cursor = conn.cursor()

        rows = cursor.execute("""
            SELECT
                ts,
                whale_net,
                exchange_net,
                price,
                price_15m,
                price_1h
            FROM research_market
            WHERE price_15m IS NOT NULL
              AND price_1h IS NOT NULL
            ORDER BY ts
        """).fetchall()

        conn.close()

        if not rows:
            await callback.message.edit_text(
                "📈 Корреляция\n\nНедостаточно данных",
                reply_markup=get_diagnostics_kb()
            )
            return

        whale_x = []
        whale_y = []

        exchange_x = []
        exchange_y = []

        ts_min = rows[0]["ts"]
        ts_max = rows[-1]["ts"]

        for r in rows:

            price = r["price"]

            if price == 0:
                continue

            # доходность
            ret_15m = (r["price_15m"] - price) / price
            ret_1h = (r["price_1h"] - price) / price

            whale_x.append(r["whale_net"])
            whale_y.append(ret_15m)

            exchange_x.append(r["exchange_net"])
            exchange_y.append(ret_1h)

        def corr(x, y):
            n = len(x)

            if n < 5:
                return 0

            mx = sum(x) / n
            my = sum(y) / n

            num = sum((a-mx)*(b-my) for a,b in zip(x,y))

            den_x = sum((a-mx)**2 for a in x) ** 0.5
            den_y = sum((b-my)**2 for b in y) ** 0.5

            if den_x == 0 or den_y == 0:
                return 0

            return num / (den_x * den_y)

        whale_corr = corr(whale_x, whale_y)
        exchange_corr = corr(exchange_x, exchange_y)

        samples = len(rows)

        text = (
            "📈 Market signal correlation\n\n"

            f"samples: {samples}\n"
            f"period: {time.strftime('%Y-%m-%d %H:%M', time.gmtime(ts_min))}"
            f" → {time.strftime('%Y-%m-%d %H:%M', time.gmtime(ts_max))}\n\n"

            f"🧠 whale_net → price_15m\n"
            f"corr: {whale_corr:.3f}\n\n"

            f"📊 exchange_net → price_1h\n"
            f"corr: {exchange_corr:.3f}\n\n"
        )

        # интерпретация
        def explain(v):
            a = abs(v)

            if a > 0.6:
                return "🔥 сильная корреляция"
            elif a > 0.3:
                return "⚠️ слабая корреляция"
            else:
                return "❌ почти нет связи"

        text += (
            f"whale: {explain(whale_corr)}\n"
            f"exchange: {explain(exchange_corr)}"
        )

        await callback.message.edit_text(
            text,
            reply_markup=get_diagnostics_kb()
        )

    except Exception as e:
        logger.exception(e)

        await callback.message.edit_text(
            "❌ Ошибка расчета корреляции",
            reply_markup=get_admin_to_main_bt()
        )