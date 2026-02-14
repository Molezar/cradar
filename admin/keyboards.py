from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_admin_to_main_bt():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_main")]
    ])


def get_admin_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💾 Скачать БД", callback_data="admin:download_db_confirm")],
        [InlineKeyboardButton(text="📜 Скачать лог миграций", callback_data="admin:download_migrations_log_confirm")],
        [InlineKeyboardButton(text="📂 Volume files", callback_data="admin:view_volume")]
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