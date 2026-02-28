# admin/messages.py
from aiogram import types
from aiogram.fsm.context import FSMContext
from logger import get_logger
from config import Config
from admin.signal.messages import handle_new_balance  # метод из signal/messages.py

logger = get_logger(__name__)
ADMIN_ID = Config.ADMIN_ID

async def handle_admin_messages(message: types.Message, state: FSMContext):
    """Хендлер сообщений админа, делегируем по FSM."""
    try:
        if message.from_user.id != ADMIN_ID:
            await message.reply("🚫 Доступ запрещен")
            return

        current_state = await state.get_state()

        # --- проверяем состояние ---
        if current_state == BalanceStates.awaiting_new_balance.state:
            await handle_new_balance(message, state)

    except Exception as e:
        logger.exception(f"Admin message handler error: {e}")
        await message.reply("⚠️ Ошибка обработки сообщения")


def setup_admin_messages(dp):
    """Регистрация хендлера сообщений админа."""
    dp.message.register(handle_admin_messages)