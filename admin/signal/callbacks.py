import time
import aiohttp
from config import Config
from aiogram import types
from logger import get_logger
from database.database import get_db
from .keyboards import get_signal_kb
from bot import get_current_price
logger = get_logger(__name__)

DEFAULT_LEVERAGE = 5
RISK_PER_TRADE = 0.02

async def calculate_signal():
    # берем текущую цену
    price = await get_current_price()
    logger.info(f"[SIGNAL] Current price: {price}")

    # берём прогноз
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(Config.API_URL + "/prediction") as resp:
                if resp.status != 200:
                    raise ValueError(f"Prediction API returned status {resp.status}")
                data = await resp.json()
                logger.info(f"[SIGNAL] Prediction data received: {data}")
        except Exception as e:
            logger.error(f"[SIGNAL] Failed to fetch prediction: {e}")
            # fallback к демо-сигналу
            logger.info(f"[SIGNAL] Using fallback demo signal")
            return "LONG", price, price * 0.98, price * 1.04, DEFAULT_LEVERAGE

    # пример выбора окна с наибольшим положительным прогнозом
    best_window = None
    best_pct = 0
    for w, v in data.items():
        if v["pct"] > best_pct:
            best_pct = v["pct"]
            best_window = w

    # направление: если прогноз >0 → LONG, <0 → SHORT
    direction = "LONG" if best_pct > 0 else "SHORT"
    entry = price
    stop = price * (0.98 if direction=="LONG" else 1.02)
    take = price * (1.04 if direction=="LONG" else 0.96)
    leverage = DEFAULT_LEVERAGE

    logger.info(f"[SIGNAL] Calculated signal: {direction}, entry: {entry}, stop: {stop}, take: {take}, leverage: {leverage}")
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

        # --- получаем сигнал ---
        direction, entry, stop, take, leverage = await calculate_signal()  # обязательно await!

        # --- мини-лог для проверки онлайн данных ---
        log_msg = (
            f"🔍 <b>Debug Signal Check</b>\n"
            f"Direction: {direction}\n"
            f"Entry: {entry}\n"
            f"Stop: {stop}\n"
            f"Take: {take}\n"
            f"Leverage: {leverage}x"
        )
        await callback.message.answer(log_msg, parse_mode="HTML")

        balance = get_demo_balance()
        position_size = calculate_position_size(balance, entry, stop)
        save_signal(direction, entry, stop, take, leverage, position_size)

        # --- основной текст сигнала ---
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