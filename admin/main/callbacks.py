import os
from datetime import datetime
from zoneinfo import ZoneInfo
from aiogram.types import FSInputFile
from config import Config
from logger import get_logger
from admin.keyboards import get_admin_to_main_bt

logger = get_logger(__name__)


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