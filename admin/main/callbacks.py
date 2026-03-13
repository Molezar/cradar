# admin/main/callbacks.py
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from aiogram.types import FSInputFile
from config import Config
from logger import get_logger
from admin.keyboards import get_admin_to_main_bt
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
            reply_markup=get_admin_to_main_bt()
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
            reply_markup=get_admin_to_main_bt()
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
            reply_markup=get_admin_to_main_bt()
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
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                SUM(CASE WHEN flow_type = 'inflow' THEN btc ELSE 0 END) as inflow,
                SUM(CASE WHEN flow_type = 'outflow' THEN btc ELSE 0 END) as outflow
            FROM exchange_flow
            WHERE ts > CAST(strftime('%s','now') AS INTEGER) - 3600
        """)

        row = cursor.fetchone()
        conn.close()

        inflow = row["inflow"] or 0
        outflow = row["outflow"] or 0
        net = inflow - outflow

        text = (
            "📈 Exchange flow (last 1h)\n\n"
            f"⬇️ inflow: {inflow:.2f} BTC\n"
            f"⬆️ outflow: {outflow:.2f} BTC\n\n"
            f"📊 net flow: {net:.2f} BTC\n\n"
        )

        if net > 0:
            text += "⚠️ давление продаж (BTC поступает на биржи)"
        elif net < 0:
            text += "🚀 давление покупок (BTC выводится с бирж)"
        else:
            text += "➖ нейтральный поток"

        await callback.message.edit_text(
            text,
            reply_markup=get_admin_to_main_bt()
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
            WHERE ef.ts > strftime('%s','now') - 900
            AND c.cluster_type = 'EXCHANGE'
            GROUP BY ef.flow_type
        """)

        rows = cursor.fetchall()
        conn.close()

        inflow = 0
        outflow = 0

        for r in rows:
            if r["flow_type"] == "inflow":
                inflow += r["total_btc"] or 0
            elif r["flow_type"] == "outflow":
                outflow += r["total_btc"] or 0

        net = inflow - outflow

        text = (
            "🧠 Whale pressure (15m)\n\n"
            f"⬇️ whale → exchange: {inflow:.2f} BTC\n"
            f"⬆️ exchange → whale: {outflow:.2f} BTC\n\n"
            f"📊 net: {net:.2f} BTC\n\n"
        )

        if net > 100:
            text += "🔥 сильное давление продаж"
        elif net > 20:
            text += "⚠️ умеренное давление продаж"
        elif net < -100:
            text += "🚀 сильное давление покупок"
        elif net < -20:
            text += "📈 умеренное давление покупок"
        else:
            text += "➖ нейтральное давление"

        await callback.message.edit_text(
            text,
            reply_markup=get_admin_to_main_bt()
        )

    except Exception as e:
        logger.exception(e)
        await callback.message.edit_text(
            "❌ Ошибка анализа whale pressure",
            reply_markup=get_admin_to_main_bt()
        )


async def handle_download_db(callback):
    """
    Отправка бэкапа базы данных через телеграм.
    Работает для aiogram v3.
    """
    try:
        db_path = Config.DB_PATH

        if not os.path.exists(db_path):
            await callback.message.edit_text(
                "⚠️ Файл базы данных не найден.",
                reply_markup=get_admin_to_main_bt()
            )
            return

        ts = datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%Y-%m-%d_%H-%M-%S")
        base_name = os.path.basename(db_path)
        name, ext = os.path.splitext(base_name)

        # Добавляем ENV в имя файла
        new_filename = f"{name}_{Config.ENV}_{ts}{ext}"

        # Отправка файла
        await callback.bot.send_document(
            chat_id=callback.from_user.id,
            document=FSInputFile(db_path, filename=new_filename),
            caption=f"📦 Бэкап базы данных\nИмя: {new_filename}"
        )

    except Exception as e:
        logger.exception(f"Ошибка при отправке базы данных: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка при отправке базы данных: {e}",
            reply_markup=get_admin_to_main_bt()
        )


async def handle_download_migrations_log(callback):
    """
    Отправка лога миграций через телеграм.
    """
    try:
        path = "migrations.log"
        if not os.path.exists(path):
            await callback.message.edit_text(
                "⚠️ Лог не найден",
                reply_markup=get_admin_to_main_bt()
            )
            return

        ts = datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%Y-%m-%d_%H-%M-%S")
        await callback.bot.send_document(
            chat_id=callback.from_user.id,
            document=FSInputFile(path, filename=f"migrations_{ts}.log")
        )

    except Exception as e:
        logger.exception(f"Ошибка при отправке лога миграций: {e}")
        await callback.message.edit_text(
            "❌ Ошибка",
            reply_markup=get_admin_to_main_bt()
        )


async def handle_view_volume(callback):
    """
    Просмотр структуры каталога /data.
    """
    try:
        base = "/data"
        if not os.path.exists(base):
            await callback.message.edit_text(
                "⚠️ Volume не найден",
                reply_markup=get_admin_to_main_bt()
            )
            return

        out = []
        for root, dirs, files in os.walk(base):
            level = root.replace(base, "").count(os.sep)
            indent = "│  " * level
            out.append(f"{indent}📁 {os.path.basename(root) or '/data'}")
            for f in files:
                out.append(f"{indent}│  📄 {f}")

        text = "\n".join(out)
        if len(text) > 3500:
            text = text[:3500] + "\n..."

        await callback.message.edit_text(
            f"📂 Volume:\n```\n{text}\n```",
            parse_mode="Markdown",
            reply_markup=get_admin_to_main_bt()
        )

    except Exception as e:
        logger.exception(f"Ошибка при просмотре volume: {e}")
        await callback.message.edit_text(
            "❌ Ошибка",
            reply_markup=get_admin_to_main_bt()
        )