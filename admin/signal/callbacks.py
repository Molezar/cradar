# admin/signal/callbacks.py
import time
from aiogram import types
from logger import get_logger
from database.database import get_db
from services.strategies import AggressiveStrategy
from aiogram.fsm.context import FSMContext
from aiogram import Dispatcher
from services.price import get_current_price
from utils import calculate_system_stats
from admin.keyboards import get_admin_to_main_bt
from .keyboards import (
    get_signal_kb,
    get_reset_stats_kb,
    get_reset_stats_confirm_kb,
    get_auto_mode_kb
)

logger = get_logger(__name__)

DEFAULT_LEVERAGE = 5
RISK_PER_TRADE = 0.03

def get_auto_mode():
    conn = None
    try:
        conn = get_db()

        row = conn.execute(
            "SELECT auto_mode FROM bot_settings WHERE id=1"
        ).fetchone()

        return bool(row["auto_mode"]) if row else False

    finally:
        if conn:
            conn.close()    

def set_auto_mode(value: bool):
    conn = None
    try:
        conn = get_db()

        conn.execute(
            "UPDATE bot_settings SET auto_mode=? WHERE id=1",
            (1 if value else 0,)
        )

        conn.commit()

    finally:
        if conn:
            conn.close()

async def auto_menu(callback: types.CallbackQuery):
    await callback.answer()
    auto = get_auto_mode()

    text = "🤖 <b>Авто режим</b>\n\n"
    text += "🟢 Включен" if auto else "🔴 Выключен"

    await callback.message.edit_text(
        text,
        reply_markup=get_auto_mode_kb(auto),
        parse_mode="HTML"
    )

async def auto_start(callback: types.CallbackQuery):
    await callback.answer()

    set_auto_mode(True)

    await callback.message.answer("🚀 Авто режим включен")

    # если нет открытой сделки — запускаем первую
    if not has_open_trade():
        await handle_signal(callback)

async def auto_stop(callback: types.CallbackQuery):
    await callback.answer()

    set_auto_mode(False)

    pnl = await close_open_trade_by_market()

    if pnl is None:
        await callback.message.answer(
            "⛔ Авто режим выключен.\nОткрытых сделок нет."
        )
    else:
        await callback.message.answer(
            f"⛔ Авто режим выключен.\n"
            f"Сделка закрыта по рынку.\n"
            f"PnL: {pnl:+.2f} USDT"
        )
        
async def close_open_trade_by_market():
    """
    Закрывает последнюю открытую сделку по текущей цене.
    Возвращает pnl или None если сделки нет.
    """

    conn = None
    try:
        conn = get_db()

        row = conn.execute("""
            SELECT * FROM trade_signals
            WHERE status='OPEN'
            ORDER BY created_at DESC
            LIMIT 1
        """).fetchone()

        if not row:
            return None

        price = await get_current_price()

        direction = row["direction"]
        entry = row["entry"]
        position_size = row["position_size"]
        trade_id = row["id"]

        pnl = (
            (price - entry) * position_size
            if direction == "LONG"
            else (entry - price) * position_size
        )

        conn.execute("""
            UPDATE trade_signals
            SET status='CANCELLED', result=?
            WHERE id=?
        """, (pnl, trade_id))

        conn.execute("""
            UPDATE demo_account
            SET balance = balance + ?,
                updated_at=strftime('%s','now')
            WHERE id=1
        """, (pnl,))

        conn.commit()

        return pnl

    finally:
        if conn:
            conn.close()
            
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
    await callback.answer()

    try:
        result = await generate_and_save_signal()

        # Проверяем, есть ли уже открытая сделка
        if result == "already_open":
            # Получаем данные текущей открытой сделки из БД
            conn = None
            try:
                conn = get_db()
                trade = conn.execute("""
                    SELECT direction, entry, stop, take, leverage, 
                           position_size, created_at
                    FROM trade_signals 
                    WHERE status = 'OPEN' 
                    ORDER BY created_at DESC 
                    LIMIT 1
                """).fetchone()
                
                if trade:
                    # Получаем текущий баланс
                    balance = get_demo_balance()
                    
                    # Формируем текст с информацией о текущей открытой сделке
                    text = (
                        f"⚠️ <b>Уже есть открытая сделка</b>\n\n"
                        f"📊 <b>Баланс:</b> {balance:.2f} USDT\n\n"
                        f"🎯 <b>Рекомендация:</b> {trade['direction']}\n"
                        f"📍 Entry: {trade['entry']}\n"
                        f"🛑 Stop: {trade['stop']}\n"
                        f"🎯 Take: {trade['take']}\n"
                        f"📈 Плечо: {trade['leverage']}x\n"
                        f"💰 Размер позиции: {trade['position_size']:.6f} BTC\n"
                        f"⚠ Риск: {RISK_PER_TRADE*100:.0f}%"
                    )
                    
                    await callback.message.edit_text(
                        text,
                        reply_markup=get_signal_kb(),
                        parse_mode="HTML"
                    )
                else:
                    # Если по какой-то причине сделки нет в БД, но функция вернула already_open
                    await callback.message.answer(
                        "⚠️ Уже есть открытая сделка.",
                        reply_markup=get_signal_kb()
                    )
                return
                
            finally:
                if conn:
                    conn.close()

        if result is None:
            await callback.message.answer("⚖️ Сейчас нет чёткого сигнала. Рынок во флэте.")
            return

        # внутри блока, где result – словарь с новым сигналом
        raw_score = result['raw_score']
        total_score = result['total_score']
        threshold = result['threshold']
        above_below = "ВЫШЕ" if abs(total_score) >= threshold else "НИЖЕ"   # сравниваем total_score с порогом
        
        text = (
            f"📊 <b>Баланс:</b> {result['balance']:.2f} USDT\n\n"
            f"🎯 <b>Рекомендация:</b> {result['direction']}\n"
            f"📍 Entry: {result['entry']}\n"
            f"🛑 Stop: {result['stop']}\n"
            f"🎯 Take: {result['take']}\n"
            f"📈 Плечо: {result['leverage']}x\n"
            f"💰 Размер позиции: {result['position_size']:.6f} BTC\n"
            f"⚠ Риск: {RISK_PER_TRADE*100:.0f}%\n\n"
            f"📊 Сырой сигнал: {raw_score:.3f}\n"
            f"📊 Сила сигнала: {abs(total_score):.1f} (порог {threshold:.3f}) – {above_below} порога"
        )

        await callback.message.edit_text(
            text,
            reply_markup=get_signal_kb(),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.exception(f"Signal error: {e}")
        await callback.message.answer("⚠️ Ошибка расчёта сигнала")

async def handle_advice(callback: types.CallbackQuery):
    await callback.answer()

    try:
        result = await generate_signal()

        if result is None:
            await callback.message.answer("⚖️ Сейчас нет чёткого сигнала. Рынок во флэте.")
            return
        
        raw_score = result['raw_score']
        total_score = result['total_score']
        threshold = result['threshold']
        above_below = "ВЫШЕ" if abs(total_score) >= threshold else "НИЖЕ"
        
        text = (
            f"📊 <b>Баланс:</b> {result['balance']:.2f} USDT\n\n"
            f"🎯 <b>Рекомендация:</b> {result['direction']}\n"
            f"📍 Entry: {result['entry']}\n"
            f"🛑 Stop: {result['stop']}\n"
            f"🎯 Take: {result['take']}\n"
            f"📈 Плечо: {result['leverage']}x\n"
            f"💰 Размер позиции: {result['position_size']:.6f} BTC\n"
            f"⚠ Риск: {RISK_PER_TRADE*100:.0f}%\n\n"
            f"📊 Сырой сигнал: {raw_score:.3f}\n"
            f"📊 Сила сигнала: {abs(total_score):.1f} (порог {threshold:.3f}) – {above_below} порога"
        )

        await callback.message.edit_text(
            text,
            reply_markup=get_advice_kb(),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.exception(f"Advice error: {e}")
        await callback.message.answer("⚠️ Ошибка расчёта совета")

async def handle_close_by_market(callback: types.CallbackQuery):
    await callback.answer()

    pnl = await close_open_trade_by_market()

    if pnl is None:
        await callback.message.answer("⚠️ Нет открытой сделки.")
        return

    percent = 0

    # пересчитываем статистику
    stats = calculate_system_stats()

    emoji = "🟢" if pnl > 0 else "🔴"

    msg = (
        f"{emoji} <b>Сделка закрыта по рынку</b>\n\n"
        f"💎 PnL: <b>{pnl:+.2f} USDT</b>\n"
        f"💼 Баланс: <b>{stats['balance']:.2f} USDT</b>\n\n"

        f"━━━━━━━━━━━━━━\n"
        f"📊 <b>System Stats</b>\n"
        f"Всего сделок: {stats['total_trades']}\n"
        f"TP: {stats['wins']} | SL: {stats['losses']}\n"
        f"Winrate: {stats['winrate']}%\n"
        f"💰 Total PnL: {stats['total_pnl']:+.2f} USDT"
    )

    await callback.message.answer(msg, parse_mode="HTML")

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

async def generate_and_save_signal():
    if has_open_trade():
        return "already_open"

    strategy = AggressiveStrategy()
    trade_data = await strategy.generate_signal()

    if trade_data is None:
        return None

    direction = trade_data["direction"]
    entry = trade_data["entry"]
    stop = trade_data["stop"]
    take = trade_data["take"]
    leverage = trade_data["leverage"]
    raw_score = trade_data["raw_score"]
    threshold = trade_data["threshold"]
    total_score = trade_data["total_score"]
    
    balance = get_demo_balance()
    position_size = calculate_position_size(balance, entry, stop)

    save_signal(direction, entry, stop, take, leverage, position_size)

    return {
        "direction": direction,
        "entry": entry,
        "stop": stop,
        "take": take,
        "leverage": leverage,
        "position_size": position_size,
        "balance": balance,
        "raw_score": raw_score,
        "threshold": threshold,
        "total_score": total_score
    }
    
async def generate_signal():

    strategy = AggressiveStrategy()
    trade_data = await strategy.generate_signal()

    direction = trade_data["direction"]
    entry = trade_data["entry"]
    stop = trade_data["stop"]
    take = trade_data["take"]
    leverage = trade_data["leverage"]
    raw_score = trade_data["raw_score"]
    threshold = trade_data["threshold"]
    total_score = trade_data["total_score"]
    
    balance = 1000
    position_size = calculate_position_size(balance, entry, stop)


    return {
        "direction": direction,
        "entry": entry,
        "stop": stop,
        "take": take,
        "leverage": leverage,
        "position_size": position_size,
        "balance": balance,
        "raw_score": raw_score,
        "threshold": threshold,
        "total_score": total_score
    }