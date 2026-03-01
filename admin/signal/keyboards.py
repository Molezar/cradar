# admin/signal/keyboards.py
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
    
def get_reset_stats_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 Обнулить статистику",
                    callback_data="admin:reset_stats_confirm"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="admin_main"
                )
            ]
        ]
    )

def get_reset_stats_confirm_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, обнулить",
                    callback_data="admin:reset_stats"
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="admin:show_balance"
                )
            ]
        ]
    )