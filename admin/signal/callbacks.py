import time
from aiogram import types
from logger import get_logger
from database.database import get_db
from .keyboards import get_signal_kb
from services.strategies import AggressiveStrategy
from aiogram.fsm.context import FSMContext

logger = get_logger(__name__)

DEFAULT_LEVERAGE = 5
RISK_PER_TRADE = 0.02
    

def get_demo_balance():
    conn = None
    try:
        conn = get_db()
        row = conn.execute("SELECT balance FROM demo_account WHERE id=1").fetchone()
        return row["balance"] if row else 1000
    finally:
        if conn:
            conn.close()


def has_open_trade():
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
    stop_distance = abs(entry - stop)
    if stop_distance == 0:
        return 0
    risk_amount = balance * RISK_PER_TRADE
    return risk_amount / stop_distance


def save_signal(direction, entry, stop, take, leverage, position_size):
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


async def handle_edit_balance(callback: types.CallbackQuery, state: FSMContext):
    """Отправляем сообщение с просьбой ввести новый баланс"""
    await callback.answer()
    await callback.message.answer("💰 Введите новый баланс демо-счёта (только цифры):")
    # ✅ используем State напрямую
    from admin.callbacks import BalanceStates
    await state.set_state(BalanceStates.awaiting_new_balance)