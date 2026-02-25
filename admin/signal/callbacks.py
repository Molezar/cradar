import time
from aiogram import types
from logger import get_logger
from database.database import get_db
from .keyboards import get_signal_kb

logger = get_logger(__name__)

DEFAULT_LEVERAGE = 5


def calculate_signal():
    """
    Пока простая логика.
    Позже подключим Binance и risk engine.
    """

    direction = "LONG"
    entry = 50000
    stop = 49000
    take = 52000
    leverage = DEFAULT_LEVERAGE

    return direction, entry, stop, take, leverage


def get_demo_balance():
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT balance FROM demo_account WHERE id = 1")
    row = c.fetchone()

    balance = row["balance"] if row else 1000
    conn.close()

    return balance


def save_signal(direction, entry, stop, take, leverage):
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        INSERT INTO trade_signals 
        (created_at, direction, entry, stop, take, leverage)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        int(time.time()),
        direction,
        entry,
        stop,
        take,
        leverage
    ))

    conn.commit()
    conn.close()


async def handle_signal(callback: types.CallbackQuery):
    await callback.answer()

    try:
        direction, entry, stop, take, leverage = calculate_signal()

        # 🔹 Сохраняем сигнал
        save_signal(direction, entry, stop, take, leverage)

        # 🔹 Получаем баланс
        balance = get_demo_balance()

        text = (
            f"📊 <b>Демо-баланс:</b> {balance:.2f} USDT\n\n"
            f"🎯 <b>Рекомендация:</b> {direction}\n"
            f"📍 Entry: {entry}\n"
            f"🛑 Stop: {stop}\n"
            f"🎯 Take: {take}\n"
            f"📈 <b>Плечо:</b> {leverage}x"
        )

        await callback.message.edit_text(
            text,
            reply_markup=get_signal_kb(),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.exception(f"Signal error: {e}")
        await callback.message.answer("⚠️ Ошибка расчёта сигнала")