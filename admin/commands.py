from aiogram import types
from aiogram.filters import Command
from config import Config
from .keyboards import get_admin_main_kb
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from config import Config
from bot import subscribers
from logger import get_logger

logger = get_logger(__name__)
ADMIN_ID = Config.ADMIN_ID


async def admin_panel(message: types.Message):
    try:
        if message.from_user.id != ADMIN_ID:
            await message.answer("🚫 Доступ запрещен")
            return

        await message.answer("👑 Админ-панель", reply_markup=get_admin_main_kb())
    except Exception as e:
        logger.exception(f"Admin command error: {e}")
        await message.answer("⚠️ Ошибка открытия админ панели")

async def start_subscribe(message: types.Message):
    subscribers.add(message.chat.id)

    logger.info(f"User {message.chat.id} started the bot")

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(
                text="Open MiniApp",
                web_app=WebAppInfo(url=WEBAPP_URL)
            )]
        ],
        resize_keyboard=True
    )

    await message.answer(
        "🧠 <b>Crypto Radar activated</b>\nWhale flow alerts enabled 👇",
        reply_markup=keyboard
    )

def setup_admin_commands(dp):
    dp.message.register(admin_panel, Command("adminmycrypto"))
    dp.message.register(start_subscribe, Command("start"))