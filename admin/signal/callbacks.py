# admin/signal/callbacks.py
import time
from aiogram import types
from logger import get_logger
from database.database import get_db
from services.strategies import AggressiveStrategy
from aiogram.fsm.context import FSMContext
from aiogram import Dispatcher
from utils import calculate_system_stats
from admin.keyboards import get_admin_to_main_bt
from .keyboards import (
    get_signal_kb,
    get_reset_stats_kb,
    get_reset_stats_confirm_kb
)

logger = get_logger(__name__)

DEFAULT_LEVERAGE = 5
RISK_PER_TRADE = 0.03
    

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
        
        strategy = AggressiveStrategy()
        result = await strategy.generate_signal()
        logger.info(f"Strategy result: {result}")
        
        if result is None:
            await callback.message.answer("⚖️ Сейчас нет чёткого сигнала. Рынок во флэте.")
            return
        
        direction, entry, stop, take, leverage = result

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

async def handle_cancel_trade(
    callback: types.CallbackQuery,
    refresh: bool = False
):
    await callback.answer()

    conn = None
    try:
        conn = get_db()

        row = conn.execute("""
            SELECT id FROM trade_signals 
            WHERE status='OPEN' 
            ORDER BY created_at DESC 
            LIMIT 1
        """).fetchone()

        if not row:
            if not refresh:
                await callback.message.answer("Нет открытой сделки.")
            # если refresh=True — просто продолжаем
        else:
            trade_id = row["id"]

            conn.execute("""
                UPDATE trade_signals
                SET status='CANCELLED'
                WHERE id=?
            """, (trade_id,))

            conn.commit()

            if not refresh:
                await callback.message.answer(
                    "❌ Сделка закрыта вручную (CANCELLED)."
                )

    except Exception as e:
        logger.exception(f"Cancel error: {e}")
        await callback.message.answer("❌ Ошибка при отмене сделки")
        return

    finally:
        if conn:
            conn.close()

    if refresh:
        await handle_signal(callback)

async def handle_refresh_signal(callback: types.CallbackQuery):
    await handle_cancel_trade(callback, refresh=True)
    
async def handle_edit_balance(callback: types.CallbackQuery):
    """Отправляет сообщение с просьбой ввести новый баланс."""
    await callback.answer()
    await callback.message.answer("💰 Введите новый баланс демо-счёта (только цифры):")
    
    state: FSMContext = Dispatcher.get_current().current_state(chat=callback.message.chat.id)
    await state.set_state("awaiting_new_balance")

async def show_demo_balance(callback: types.CallbackQuery):
    await callback.answer()

    try:
        stats = calculate_system_stats()

        text = (
            "📊 <b>Системная статистика</b>\n\n"

            f"💰 <b>Баланс:</b> {stats['balance']:.2f} USDT\n"
            f"📈 <b>Total PnL:</b> {stats['total_pnl']:.2f} USDT\n\n"

            f"📊 <b>Сделки:</b>\n"
            f"• Всего: {stats['total_trades']}\n"
            f"• TP: {stats['wins']}\n"
            f"• SL: {stats['losses']}\n"
            f"• Winrate: {stats['winrate']}%\n"
        )

        await callback.message.edit_text(
            text,
            reply_markup=get_reset_stats_kb(),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.exception(f"Show balance error: {e}")
        await callback.message.answer("❌ Ошибка получения статистики")
        
async def confirm_reset_stats(callback: types.CallbackQuery):
    await callback.answer()

    await callback.message.edit_text(
        "⚠️ Вы уверены, что хотите полностью обнулить статистику?\n\n"
        "Будут удалены все сделки и сброшен баланс.",
        reply_markup=get_reset_stats_confirm_kb()
    )
    
async def reset_stats(callback: types.CallbackQuery):
    await callback.answer()

    conn = None
    try:
        conn = get_db()

        # Удаляем все сделки
        conn.execute("DELETE FROM trade_signals")

        # Сбрасываем баланс к 1000
        conn.execute("""
            UPDATE demo_account
            SET balance = 1000,
                updated_at = strftime('%s','now')
            WHERE id = 1
        """)

        conn.commit()

        await callback.message.answer("✅ Статистика успешно обнулена.")

        # Обновляем экран статистики
        await show_demo_balance(callback)

    except Exception as e:
        logger.exception(f"Reset stats error: {e}")
        await callback.message.answer("❌ Ошибка при обнулении статистики")

    finally:
        if conn:
            conn.close()