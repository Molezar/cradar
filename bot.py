import os
import asyncio
import aiohttp
import json

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
from aiogram.client.default import DefaultBotProperties

from config import Config
from logger import get_logger
from admin import setup_admin

logger = get_logger(__name__)

BOT_TOKEN = Config.BOT_TOKEN
WEBAPP_URL = Config.WEBAPP_URL
API = "http://127.0.0.1:" + os.environ.get("PORT", "8000")

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()
setup_admin(dp)

# Telegram chat_id подписчиков
subscribers = set()


# ------------------ /start ------------------

@dp.message(Command("start"))
async def start(message: types.Message):
    subscribers.add(message.chat.id)
    logger.info(f"User {message.chat.id} started the bot")

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Open MiniApp", web_app=WebAppInfo(url=WEBAPP_URL))]
        ],
        resize_keyboard=True
    )

    try:
        await message.answer("Crypto Radar 👇", reply_markup=keyboard)
    except Exception as e:
        logger.exception(f"Failed to send start message to {message.chat.id}: {e}")


# ------------------ SSE listener ------------------

async def whale_listener():
    await asyncio.sleep(2)
    logger.info("Starting whale_listener SSE task")

    buffer = ""

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(API + "/events", timeout=None) as resp:
                    async for chunk in resp.content.iter_any():
                        try:
                            text = chunk.decode("utf-8", errors="ignore")
                        except Exception:
                            continue

                        buffer += text

                        # SSE events разделяются пустой строкой
                        while "\n\n" in buffer:
                            event, buffer = buffer.split("\n\n", 1)

                            lines = event.splitlines()
                            for line in lines:
                                if not line.startswith("data:"):
                                    continue

                                raw = line[5:].strip()
                                if not raw:
                                    continue

                                try:
                                    tx = json.loads(raw)
                                except Exception as e:
                                    logger.warning(f"Bad JSON from SSE: {raw} ({e})")
                                    continue

                                # Безопасно достаём поля
                                btc = tx.get("btc")
                                txid = tx.get("txid")

                                if not btc or not txid:
                                    logger.warning(f"Incomplete tx data: {tx}")
                                    continue

                                try:
                                    btc = float(btc)
                                except:
                                    logger.warning(f"Invalid btc value: {btc}")
                                    continue

                                msg = f"🐋 {btc:.2f} BTC\n{txid[:12]}…"
                                logger.info(f"Whale tx: {btc} BTC {txid}")

                                for cid in list(subscribers):
                                    try:
                                        await bot.send_message(cid, msg)
                                    except Exception as e:
                                        logger.warning(f"Failed to send to {cid}: {e}")
                                        subscribers.discard(cid)

        except Exception as e:
            logger.error(f"SSE connection error: {e}", exc_info=True)
            await asyncio.sleep(3)


# ------------------ main ------------------

async def main():
    logger.info("Bot main started")
    asyncio.create_task(whale_listener())
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.exception(f"Bot stopped with error: {e}")