# admin/diagnostics/callbacks.py
import time
from config import Config
from logger import get_logger
from admin.keyboards import get_admin_to_main_bt
from .keyboards import get_diagnostics_kb
from database.database import get_db

logger = get_logger(__name__)

async def handle_fix_null_clusters(callback):
    """
    Чистит NULL в whale_classification + удаляет дубли
    + проверяет и удаляет проблемный индекс exchange_flow
    (без падений, идемпотентно)
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        # ==============================
        # ===== SAFE INDEX CHECK =======
        # ==============================
        indexes_before = []
        indexes_after = []

        try:
            rows = cursor.execute("PRAGMA index_list(exchange_flow);").fetchall()
            indexes_before = [r[1] for r in rows]

            # пробуем удалить индекс (если вдруг остался)
            cursor.execute("DROP INDEX IF EXISTS ux_exchange_flow_ts_cluster_flow;")

            rows = cursor.execute("PRAGMA index_list(exchange_flow);").fetchall()
            indexes_after = [r[1] for r in rows]

        except Exception:
            # вообще не критично — не ломаем основной процесс
            pass

        # ==============================
        # ===== FIX NULL CLUSTERS ======
        # ==============================

        # фиктивный кластер
        cursor.execute("""
            INSERT OR IGNORE INTO clusters (id, cluster_type, name, created_at, last_updated)
            VALUES (0, 'unknown', 'UNKNOWN', strftime('%s','now'), strftime('%s','now'))
        """)

        # сколько было NULL
        cursor.execute("""
            SELECT COUNT(*) as cnt
            FROM whale_classification
            WHERE from_cluster IS NULL OR to_cluster IS NULL
        """)
        before_null = cursor.fetchone()["cnt"]

        # замена NULL
        cursor.execute("""
            UPDATE whale_classification
            SET from_cluster = 0
            WHERE from_cluster IS NULL
        """)
        cursor.execute("""
            UPDATE whale_classification
            SET to_cluster = 0
            WHERE to_cluster IS NULL
        """)

        conn.commit()

        # ==============================
        # ===== REMOVE DUPLICATES ======
        # ==============================

        cursor.execute("""
            DELETE FROM whale_classification
            WHERE rowid NOT IN (
                SELECT MIN(rowid)
                FROM whale_classification
                GROUP BY txid, flow_type, from_cluster, to_cluster
            )
        """)
        conn.commit()

        # ==============================
        # ===== POST CHECK ============
        # ==============================

        cursor.execute("""
            SELECT COUNT(*) as cnt
            FROM whale_classification
            WHERE from_cluster IS NULL OR to_cluster IS NULL
        """)
        after_null = cursor.fetchone()["cnt"]

        cursor.execute("""
            SELECT COUNT(*) as cnt
            FROM (
                SELECT txid, flow_type, from_cluster, to_cluster, COUNT(*) as c
                FROM whale_classification
                GROUP BY txid, flow_type, from_cluster, to_cluster
                HAVING c > 1
            )
        """)
        duplicates = cursor.fetchone()["cnt"]

        conn.close()

        # ==============================
        # ===== REPORT ================
        # ==============================

        text = (
            "🛠 FIX NULL clusters + remove duplicates\n\n"
            f"NULL before: {before_null}\n"
            f"NULL after: {after_null}\n"
            f"duplicates remaining: {duplicates}\n\n"
        )

        # индекс инфо
        if indexes_before or indexes_after:
            text += "📊 exchange_flow indexes:\n"
            text += f"before: {indexes_before}\n"
            text += f"after: {indexes_after}\n\n"

        # итог
        if after_null == 0 and duplicates == 0:
            text += "✅ NULL очищены и дубли удалены"
        elif after_null > 0:
            text += "⚠️ есть оставшиеся NULL"
        elif duplicates > 0:
            text += "⚠️ есть оставшиеся дубли"
        else:
            text += "ℹ️ изменений не было нужно"

        await callback.message.edit_text(
            text,
            reply_markup=get_diagnostics_kb()
        )

    except Exception as e:
        logger.exception(e)
        await callback.message.edit_text(
            "❌ Ошибка очистки NULL / индекса / дублей",
            reply_markup=get_admin_to_main_bt()
        )
        
async def handle_tables_info(callback):
    """
    Показывает количество записей и список колонок в каждой таблице БД
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
                # количество записей
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]

                # колонки (PRAGMA)
                cursor.execute(f"PRAGMA table_info({table})")
                cols = cursor.fetchall()

                # форматируем: name(type)
                col_names = []
                for col in cols:
                    name = col[1]
                    col_type = col[2]
                    col_names.append(f"{name}({col_type})")

                cols_str = ", ".join(col_names)

                lines.append(f"📄 {table} ({count})\n   └ {cols_str}")

            except Exception as e:
                logger.exception(f"Ошибка таблицы {table}: {e}")
                lines.append(f"📄 {table}: error")

        conn.close()

        text = "📊 Таблицы БД:\n\n" + "\n\n".join(lines)

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
    exchange_net_ratio → price_1h
    + signal = exchange_ratio * volatility
    + кластерная концентрация
    + P(up|strong inflow), P(down|strong outflow)
    """

    try:
        conn = get_db()
        cursor = conn.cursor()

        rows = cursor.execute("""
            SELECT ts, whale_net, exchange_net, exchange_net_ratio,
                   volatility, cluster_concentration, price, price_15m, price_1h
            FROM research_market
            WHERE price_15m IS NOT NULL AND price_1h IS NOT NULL
            ORDER BY ts
        """).fetchall()
        conn.close()

        if not rows:
            await callback.message.edit_text(
                "📈 Корреляция\n\nНедостаточно данных",
                reply_markup=get_diagnostics_kb()
            )
            return

        # --------------------------
        # percentiles p90/p95
        # --------------------------
        def percentile(arr, p, default=0):
            if len(arr) < 20: return default
            return sorted(arr)[int(len(arr)*p)]

        signals = [abs((r["exchange_net_ratio"] or 0)*(r["volatility"] or 0)) for r in rows]
        clusters = [r["cluster_concentration"] or 0 for r in rows]

        sig_p90, sig_p95 = percentile(signals, 0.9, 0.001), percentile(signals, 0.95, 0.002)
        clust_p90, clust_p95 = percentile(clusters, 0.9, 0.1), percentile(clusters, 0.95, 0.2)

        # --------------------------
        # strong signal stats
        # --------------------------
        def safe_delta(r):
            if r["price"] is None or r["price_1h"] is None:
                return None
            return (r["price_1h"] - r["price"]) / r["price"]

        strong_inflow_up = sum(
            1 for r in rows
            if r["exchange_net_ratio"] is not None and r["exchange_net_ratio"] > sig_p90
               and (delta := safe_delta(r)) is not None and delta > 0
        )

        strong_outflow_down = sum(
            1 for r in rows
            if r["exchange_net_ratio"] is not None and r["exchange_net_ratio"] < -sig_p90
               and (delta := safe_delta(r)) is not None and delta < 0
        )

        strong_total = sum(1 for r in rows if r["exchange_net_ratio"] is not None and abs(r["exchange_net_ratio"]) > sig_p90)
        p_up = strong_inflow_up / strong_total*100 if strong_total else 0
        p_down = strong_outflow_down / strong_total*100 if strong_total else 0

        # --------------------------
        # text
        # --------------------------
        text = (
            f"📊 Market correlation\n\n"
            f"samples: {len(rows)}\n"
            f"signal p90: {sig_p90:.5f}, p95: {sig_p95:.5f}\n"
            f"cluster p90: {clust_p90:.3f}, p95: {clust_p95:.3f}\n"
            f"P(up | strong inflow): {p_up:.1f}%\n"
            f"P(down | strong outflow): {p_down:.1f}%\n"
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