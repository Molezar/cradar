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
            ],
            [
                InlineKeyboardButton(
                    text="❌ Закрыть (CANCELLED)",
                    callback_data="cancel:trade"
                ),
                InlineKeyboardButton(
                    text="💰 Закрыть по рынку",
                    callback_data="close:market"
                )
            ],
                        [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="admin:deal"
                )
            ]
        ]
    )
    
def get_advice_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Обновить совет",
                    callback_data="advice:refresh"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="admin:deal"
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
                    callback_data="admin:deal"
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

def get_auto_mode_kb(auto_enabled: bool):
    if auto_enabled:
        btn = InlineKeyboardButton(
            text="⛔ Стоп авто",
            callback_data="auto:stop"
        )
    else:
        btn = InlineKeyboardButton(
            text="🚀 Авто режим",
            callback_data="auto:start"
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="admin:deal"
                )
            ]
        ]
    )
 
def get_signal_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Совет", callback_data="advice:get")],
        [InlineKeyboardButton(text="🎯 Сигнал", callback_data="signal:get")],
        [InlineKeyboardButton(text="🤖 Авто режим", callback_data="auto:menu")],
        [InlineKeyboardButton(text="💰 Баланс", callback_data="admin:show_balance")],
        [InlineKeyboardButton(text="💰 Изменить баланс", callback_data="admin:edit_balance")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_main")]
    ])