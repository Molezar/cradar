# admin/signal/messages.py
from aiogram import types
from aiogram import types
from database.database import get_db
from logger import get_logger
from aiogram.fsm.context import FSMContext

logger = get_logger(__name__)

async def handle_new_balance(message: types.Message, state: FSMContext):
    """Обработка ввода нового баланса пользователем."""
    try:
        # пытаемся преобразовать текст в float
        new_balance = float(message.text)
        if new_balance <= 0:
            await message.answer("⚠ Баланс должен быть положительным числом.")
            return

        # сохраняем в БД
        conn = None
        try:
            conn = get_db()
            conn.execute("""
                UPDATE demo_account
                SET balance = ?, updated_at = strftime('%s','now')
                WHERE id = 1
            """, (new_balance,))
            conn.commit()
        finally:
            if conn:
                conn.close()

        await message.answer(f"✅ Новый баланс установлен: {new_balance:.2f} USDT")
        await state.clear()  # ✅ очищаем FSM после ввода
        
    except ValueError:
        await message.answer("⚠ Пожалуйста, введите корректное число (например, 1500.25)")
    except Exception as e:
        logger.exception(f"Ошибка при установке нового баланса: {e}")
        await message.answer("⚠ Ошибка при сохранении нового баланса.")
        await state.clear()