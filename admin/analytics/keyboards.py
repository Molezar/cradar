from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_analytics_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 Exchange flow (1h)", callback_data="admin:exchange_flow_1h")],
        [InlineKeyboardButton(text="🐋 Whale pressure (15m)", callback_data="admin:whale_pressure_15m")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_main")]
    ])