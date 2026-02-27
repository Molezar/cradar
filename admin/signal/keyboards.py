from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_signal_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Обновить сигнал",
                    callback_data="signal:refresh"
                ),
                InlineKeyboardButton(
                    text="❌ Закрыть сделку",
                    callback_data="cancel:trade"
                )
            ]
        ]
    )