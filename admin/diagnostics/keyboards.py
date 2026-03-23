from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_diagnostics_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Таблицы", callback_data="admin:tables_info")],
        [InlineKeyboardButton(text="🧩 Top clusters", callback_data="admin:top_clusters")],
        [InlineKeyboardButton(text="🧠 Cluster health (last 2h)", callback_data="admin:cluster_health")],
        [InlineKeyboardButton(text="🔬 Flow pipeline", callback_data="admin:flow_pipeline_check")],
        [InlineKeyboardButton(text="📈 Корреляция", callback_data="admin:research_correlation")],
        [InlineKeyboardButton(text="🛠 FIX NULL clusters", callback_data="admin:fix_null_clusters")],  # ← новая кнопка
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_main")]
    ])