# admin/callbacks.py
from aiogram import types
from aiogram import Dispatcher
from logger import get_logger
from database.database import init_db, get_db
from config import Config
from pathlib import Path
from migrate import run_migrations

from .keyboards import (
    get_admin_main_kb,
    get_admin_to_main_bt,
    get_download_db_confirm_kb,
    get_download_migrations_log_confirm_kb,
    get_recreate_db_confirm_kb
)
from admin.main.callbacks import (
    handle_download_db,
    handle_download_migrations_log,
    handle_view_volume
)
from admin.signal.callbacks import (
    handle_signal,
    handle_cancel_trade,
    handle_refresh_signal,
    show_demo_balance,
    confirm_reset_stats,
    reset_stats
)

from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from admin.signal.messages import handle_new_balance

class BalanceStates(StatesGroup):
    awaiting_new_balance = State()

logger = get_logger(__name__)
ADMIN_ID = Config.ADMIN_ID


async def handle_admin_callbacks(callback: types.CallbackQuery, state: FSMContext):
    """Главный callback для админ-кнопок с FSMContext переданным сверху"""
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

        elif data == "admin:recreate_db_confirm":
            await callback.message.edit_text(
                "Вы действительно хотите пересоздать базу данных? ⚠️ Все данные будут потеряны!",
                reply_markup=get_recreate_db_confirm_kb()
            )
        elif data == "admin:recreate_db":
            try:
                db_path = Config.DB_PATH
                if db_path.exists():
                    db_path.unlink()
        
                env = Config.ENV.lower()
                if env == "prod":
                    log_path = Path("/data/prod_applied_migrations.txt")
                elif env == "stag":
                    log_path = Path("/data/stag_applied_migrations.txt")
                else:
                    log_path = Path("database/applied_migrations.txt")
        
                if log_path.exists():
                    log_path.unlink()
        
                init_db()
                run_migrations()
        
                await callback.message.edit_text(
                    "✅ База данных успешно пересоздана!",
                    reply_markup=get_admin_main_kb()
                )
        
            except Exception as e:
                logger.exception(e)
                await callback.message.edit_text(
                    "❌ Ошибка при пересоздании БД",
                    reply_markup=get_admin_main_kb()
        )
        
        elif data == "signal:get":
            await handle_signal(callback)
        elif data == "cancel:trade":
            await handle_cancel_trade(callback)
        elif data == "signal:refresh":
            await handle_refresh_signal(callback)
            
        elif data == "admin:reset_stats_confirm":
            await confirm_reset_stats(callback)
        
        elif data == "admin:reset_stats":
            await reset_stats(callback)
            
        elif data == "admin:show_balance":
            await show_demo_balance(callback)
        elif data == "admin:edit_balance":
            await callback.answer()
            await callback.message.answer("💰 Введите новый баланс демо-счёта (только цифры):")
            
            # ✅ FSMContext уже передан в callback, используем его напрямую
            await state.set_state(BalanceStates.awaiting_new_balance)
        
        elif data == "admin_main":
            await callback.message.edit_text(
                "👑 Админ-панель",
                reply_markup=get_admin_main_kb()
            )

    except Exception as e:
        logger.exception(f"Admin callback error: {e}")
        await callback.message.edit_text("⚠️ Ошибка", reply_markup=get_admin_to_main_bt())


def setup_admin_callbacks(dp: Dispatcher):
    dp.callback_query.register(handle_admin_callbacks)