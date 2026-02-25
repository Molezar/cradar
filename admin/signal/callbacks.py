import time
from aiogram import types
from logger import get_logger
from database.database import get_db
from .keyboards import get_signal_kb

logger = get_logger(__name__)

DEFAULT_LEVERAGE = 5
RISK_PER_TRADE = 0.02


def calculate_signal():
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


def calculate_position_size(balance, entry, stop):
    risk_amount = balance * RISK_PER_TRADE
    stop_distance = abs(entry - stop)

    if stop_distance == 0:
        return 0

    position_size = risk_amount / stop_distance
    return position_size


def save_signal(direction, entry, stop, take, leverage, position_size):
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        INSERT INTO trade_signals 
        (created_at, direction, entry, stop, take, leverage, position_size)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        int(time.time()),
        direction,
        entry,
        stop,
        take,
        leverage,
        position_size
    ))

    conn.commit()
    conn.close()

def has_open_trade():
    conn = get_db()
    c = conn.cursor()

    row = c.execute(
        "SELECT id FROM trade_signals WHERE status='OPEN' LIMIT 1"
    ).fetchone()

    conn.close()

    return row is not None

async def handle_signal(callback: types.CallbackQuery):
    await callback.answer()

    try:
        # 🔒 Проверка на открытую сделку
        if has_open_trade():
            await callback.message.answer(
                "⚠️ Уже есть открытая сделка.\n"
                "Дождитесь её закрытия (TP или SL)."
            )
            return

        direction, entry, stop, take, leverage = calculate_signal()

        balance = get_demo_balance()

        position_size = calculate_position_size(balance, entry, stop)

        save_signal(direction, entry, stop, take, leverage, position_size)

        text = (
            f"📊 <b>Баланс:</b> {balance:.2f} USDT\n\n"
            f"🎯 <b>Рекомендация:</b> {direction}\n"
            f"📍 Entry: {entry}\n"
            f"🛑 Stop: {stop}\n"
            f"🎯 Take: {take}\n"
            f"📈 Плечо: {leverage}x\n"
            f"💰 Размер позиции: {position_size:.6f} BTC\n"
            f"⚠ Риск: 2%"
        )

        await callback.message.edit_text(
            text,
            reply_markup=get_signal_kb(),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.exception(f"Signal error: {e}")
        await callback.message.answer("⚠️ Ошибка расчёта сигнала")
        