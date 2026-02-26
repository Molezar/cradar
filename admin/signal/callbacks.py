import time
from aiogram import types
from logger import get_logger
from database.database import get_db
from .keyboards import get_signal_kb

logger = get_logger(__name__)

DEFAULT_LEVERAGE = 5
RISK_PER_TRADE = 0.02


def calculate_signal():
    """Возвращает пример сигнала (можно заменить на реальный алгоритм)."""
    direction = "LONG"
    entry = 50000
    stop = 49000
    take = 52000
    leverage = DEFAULT_LEVERAGE
    return direction, entry, stop, take, leverage


def get_demo_balance():
    """Возвращает баланс демо-счёта."""
    conn = None
    try:
        conn = get_db()
        row = conn.execute("SELECT balance FROM demo_account WHERE id=1").fetchone()
        return row["balance"] if row else 1000
    finally:
        if conn:
            conn.close()


def has_open_trade():
    """Проверяет наличие открытой сделки."""
    conn = None
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT 1 FROM trade_signals WHERE status='OPEN' LIMIT 1"
        ).fetchone()
        return row is not None
    finally:
        if conn:
            conn.close()


def calculate_position_size(balance, entry, stop):
    """Рассчитывает размер позиции по правилу риска."""
    stop_distance = abs(entry - stop)
    if stop_distance == 0:
        return 0
    risk_amount = balance * RISK_PER_TRADE
    return risk_amount / stop_distance


def save_signal(direction, entry, stop, take, leverage, position_size):
    """Сохраняет сигнал в БД."""
    conn = None
    try:
        conn = get_db()
        conn.execute("""
            INSERT INTO trade_signals 
            (created_at, direction, entry, stop, take, leverage, position_size)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            int(time.time()), direction, entry, stop, take, leverage, position_size
        ))
        conn.commit()
    finally:
        if conn:
            conn.close()


async def handle_signal(callback: types.CallbackQuery):
    """Обработка сигнала через кнопку в Telegram."""
    await callback.answer()
    try:
        if has_open_trade():
            await callback.message.answer(
                "⚠️ Уже есть открытая сделка.\nДождитесь её закрытия (TP или SL)."
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
            f"⚠ Риск: {RISK_PER_TRADE*100:.0f}%"
        )

        await callback.message.edit_text(
            text,
            reply_markup=get_signal_kb(),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.exception(f"Signal error: {e}")
        await callback.message.answer("⚠️ Ошибка расчёта сигнала")