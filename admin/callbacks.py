from aiogram import types
from logger import get_logger
from config import Config
from .keyboards import (
    get_admin_main_kb,
    get_admin_to_main_bt,
    get_download_db_confirm_kb,
    get_download_migrations_log_confirm_kb
)
from admin.main.callbacks import (
    handle_download_db,
    handle_download_migrations_log,
    handle_view_volume
)

logger = get_logger(__name__)
ADMIN_ID = Config.ADMIN_ID


async def handle_admin_callbacks(callback: types.CallbackQuery):
    await callback.answer()

    try:
        if callback.from_user.id != ADMIN_ID:
            await callback.message.edit_text("🚫 Доступ запрещен")
            return

        data = callback.data

        if data == "admin:download_db_confirm":
            await callback.message.edit_text(
                "Вы действительно хотите скачать базу данных?",
                reply_markup=get_download_db_confirm_kb()
            )

        elif data == "admin:download_db":
            await handle_download_db(callback)

        elif data == "admin:download_migrations_log_confirm":
            await callback.message.edit_text(
                "Вы действительно хотите скачать лог миграций?",
                reply_markup=get_download_migrations_log_confirm_kb()
            )

        elif data == "admin:download_migrations_log":
            await handle_download_migrations_log(callback)

        elif data == "admin:view_volume":
            await handle_view_volume(callback)

        elif data == "admin_main":
            await callback.message.edit_text(
                "👑 Админ-панель",
                reply_markup=get_admin_main_kb()
            )

    except Exception as e:
        logger.exception(f"Admin callback error: {e}")
        await callback.message.edit_text("⚠️ Ошибка", reply_markup=get_admin_to_main_bt())


def setup_admin_callbacks(dp):
    dp.callback_query.register(handle_admin_callbacks)