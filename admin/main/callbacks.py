import os
from datetime import datetime
from zoneinfo import ZoneInfo
from aiogram.types import FSInputFile
from config import Config
from logger import get_logger
from admin.keyboards import get_admin_to_main_bt

logger = get_logger(__name__)


async def handle_download_db(callback):
    try:
        db_path = Config.DB_PATH

        if not os.path.exists(db_path):
            await callback.message.edit_text("⚠️ Файл базы данных не найден.", reply_markup=get_admin_to_main_bt())
            return

        ts = datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%Y-%m-%d_%H-%M-%S")
        name = f"radar_{ts}.db"

        await callback.bot.send_document(
            callback.from_user.id,
            FSInputFile(db_path, filename=name),
            caption=f"📦 Бэкап базы данных\n{name}"
        )

    except Exception as e:
        logger.exception(e)
        await callback.message.edit_text("❌ Ошибка отправки БД", reply_markup=get_admin_to_main_bt())


async def handle_download_migrations_log(callback):
    try:
        path = "migrations.log"
        if not os.path.exists(path):
            await callback.message.edit_text("⚠️ Лог не найден", reply_markup=get_admin_to_main_bt())
            return

        ts = datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%Y-%m-%d_%H-%M-%S")
        await callback.bot.send_document(
            callback.from_user.id,
            FSInputFile(path, filename=f"migrations_{ts}.log")
        )

    except Exception as e:
        logger.exception(e)
        await callback.message.edit_text("❌ Ошибка", reply_markup=get_admin_to_main_bt())


async def handle_view_volume(callback):
    try:
        base = "/data"
        if not os.path.exists(base):
            await callback.message.edit_text("⚠️ Volume не найден", reply_markup=get_admin_to_main_bt())
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

        await callback.message.edit_text(f"📂 Volume:\n```\n{text}\n```", parse_mode="Markdown", reply_markup=get_admin_to_main_bt())

    except Exception as e:
        logger.exception(e)
        await callback.message.edit_text("❌ Ошибка", reply_markup=get_admin_to_main_bt())