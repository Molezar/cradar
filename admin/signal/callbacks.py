from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from logger import get_logger
from .keyboards import get_signal_kb

logger = get_logger(__name__)


# Заглушка расчёта сигнала (пока без Binance)
def calculate_signal():
    return {
        "direction": "LONG",
        "entry": 50000,
        "stop": 49000,
        "take": 52000,
        "balance": 1000
    }


async def handle_signal(callback: types.CallbackQuery):
    await callback.answer()

    try:
        if callback.data in ("signal:get", "signal:refresh"):
            signal = calculate_signal()

            text = (
                f"📊 <b>Текущий демо-баланс:</b> {signal['balance']} USDT\n\n"
                f"🎯 <b>Рекомендация:</b> {signal['direction']}\n"
                f"📍 Entry: {signal['entry']}\n"
                f"🛑 Stop: {signal['stop']}\n"
                f"🎯 Take: {signal['take']}\n"
            )

            await callback.message.edit_text(
                text,
                reply_markup=get_signal_kb(),
                parse_mode="HTML"
            )

    except Exception as e:
        logger.exception(f"Signal callback error: {e}")
        await callback.message.answer("⚠️ Ошибка при расчёте сигнала")