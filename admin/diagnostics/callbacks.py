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
    Анализ качества сигналов:
    whale_net → price_15m
    exchange_net → price_1h

    Реакции рынка:
    1) endpoint (цена через 1h)
    2) max move за час
    3) avg move за час
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

        whale_correct = 0
        whale_total = 0
        whale_moves = []

        exchange_correct = 0
        exchange_total = 0

        exchange_endpoint_moves = []
        exchange_max_moves = []
        exchange_avg_window_moves = []

        ts_min = rows[0]["ts"]
        ts_max = rows[-1]["ts"]

        n = len(rows)

        for i, r in enumerate(rows):

            price = r["price"]
            if price == 0:
                continue

            ret_15m = (r["price_15m"] - price) / price
            ret_1h = (r["price_1h"] - price) / price

            whale_net = r["whale_net"]
            exchange_net = r["exchange_net"]

            # ---------- корреляция ----------
            whale_x.append(whale_net)
            whale_y.append(ret_15m)

            exchange_x.append(exchange_net)
            exchange_y.append(ret_1h)

            # ---------- whale accuracy ----------
            if abs(whale_net) > 1:

                whale_total += 1
                whale_moves.append(abs(ret_15m))

                predicted = -1 if whale_net > 0 else 1
                actual = 1 if ret_15m > 0 else -1

                if predicted == actual:
                    whale_correct += 1

            # ---------- exchange accuracy ----------
            if abs(exchange_net) > 1:

                exchange_total += 1

                predicted = -1 if exchange_net > 0 else 1
                actual = 1 if ret_1h > 0 else -1

                if predicted == actual:
                    exchange_correct += 1

                # ---------- endpoint move ----------
                exchange_endpoint_moves.append(abs(ret_1h))

                # ---------- окно 1h (≈12 записей) ----------
                window = rows[i+1:i+13]

                if window:

                    prices = [w["price"] for w in window if w["price"]]

                    if prices:

                        max_price = max(prices)
                        min_price = min(prices)
                        avg_price = sum(prices) / len(prices)

                        max_move = max(
                            abs((max_price - price) / price),
                            abs((min_price - price) / price)
                        )

                        avg_move = abs((avg_price - price) / price)

                        exchange_max_moves.append(max_move)
                        exchange_avg_window_moves.append(avg_move)

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

        whale_acc = (whale_correct / whale_total * 100) if whale_total else 0
        exchange_acc = (exchange_correct / exchange_total * 100) if exchange_total else 0

        whale_avg_move = (sum(whale_moves) / len(whale_moves) * 100) if whale_moves else 0

        endpoint_avg = (sum(exchange_endpoint_moves) / len(exchange_endpoint_moves) * 100) if exchange_endpoint_moves else 0
        max_avg = (sum(exchange_max_moves) / len(exchange_max_moves) * 100) if exchange_max_moves else 0
        avg_window = (sum(exchange_avg_window_moves) / len(exchange_avg_window_moves) * 100) if exchange_avg_window_moves else 0

        samples = len(rows)

        text = (
            "📈 Market signal calibration\n\n"

            f"samples: {samples}\n"
            f"period: {time.strftime('%Y-%m-%d %H:%M', time.gmtime(ts_min))}"
            f" → {time.strftime('%Y-%m-%d %H:%M', time.gmtime(ts_max))}\n\n"

            f"🧠 whale pressure (15m)\n"
            f"corr: {whale_corr:.3f}\n"
            f"accuracy: {whale_acc:.1f}%\n"
            f"avg move: {whale_avg_move:.3f}%\n\n"

            f"📊 exchange flow (1h)\n"
            f"corr: {exchange_corr:.3f}\n"
            f"accuracy: {exchange_acc:.1f}%\n\n"

            f"reaction (endpoint): {endpoint_avg:.3f}%\n"
            f"reaction (max 1h): {max_avg:.3f}%\n"
            f"reaction (avg 1h): {avg_window:.3f}%"
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
 