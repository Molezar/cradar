# admin/keyboards.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_admin_to_main_bt():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_main")]
    ])


def get_download_db_confirm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data="admin:download_db"),
            InlineKeyboardButton(text="❌ Нет", callback_data="admin_main")
        ]
    ])


def get_download_migrations_log_confirm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, скачать", callback_data="admin:download_migrations_log"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_main")
        ]
    ])
    
def get_recreate_db_confirm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, пересоздать БД", callback_data="admin:recreate_db"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_main")
        ]
    ])

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

    return InlineKeyboardMarkup(inline_keyboard=[[btn]])
    
def get_admin_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Таблицы", callback_data="admin:tables_info")],
        [InlineKeyboardButton(text="💾 Скачать БД", callback_data="admin:download_db_confirm")],
        [InlineKeyboardButton(text="📜 Скачать лог миграций", callback_data="admin:download_migrations_log_confirm")],
        [InlineKeyboardButton(text="📂 Volume files", callback_data="admin:view_volume")],
        [InlineKeyboardButton(text="🎯 Сигнал", callback_data="signal:get")],
        [InlineKeyboardButton(text="🤖 Авто режим", callback_data="auto:menu")],
        [InlineKeyboardButton(text="💰 Баланс", callback_data="admin:show_balance")],  # 👈 НОВАЯ
        [InlineKeyboardButton(text="💰 Изменить баланс", callback_data="admin:edit_balance")],
        [InlineKeyboardButton(text="♻️ Пересоздать БД", callback_data="admin:recreate_db_confirm")]
    ])