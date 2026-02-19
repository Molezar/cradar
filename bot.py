import os
import asyncio
import aiohttp
import json
import sqlite3
import time
import ssl
import certifi

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
from aiogram.client.default import DefaultBotProperties

from config import Config
from logger import get_logger
from admin import setup_admin

print("ENV:", Config.ENV)
print("API_URL:", Config.API_URL)
print("WEBAPP_URL:", Config.WEBAPP_URL)
print("PORT:", os.environ.get("PORT"))

logger = get_logger(__name__)

BOT_TOKEN = Config.BOT_TOKEN
WEBAPP_URL = Config.WEBAPP_URL

if Config.IS_PROD:
    API = os.getenv("API_URL")
    if not API:
        raise ValueError("API_URL env variable is missing on PROD!")
    ssl_context = ssl.create_default_context(cafile=certifi.where())
else:
    API = "http://127.0.0.1:" + os.environ.get("PORT", "8000")
    ssl_context = None

MIN_WHALE_BTC = Config.MIN_WHALE_BTC
ALERT_WHALE_BTC = Config.ALERT_WHALE_BTC

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()
setup_admin(dp)

subscribers = set()


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

    await message.answer(
        "🧠 <b>Crypto Radar activated</b>\nWhale flow alerts enabled 👇",
        reply_markup=keyboard
    )


async def whale_listener():
    await asyncio.sleep(2)
    logger.info("Starting whale_listener SSE task")

    buffer = ""

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(API + "/events", timeout=None, ssl=ssl_context) as resp:
                    async for chunk in resp.content.iter_any():
                        text = chunk.decode("utf-8", errors="ignore")
                        buffer += text

                        while "\n\n" in buffer:
                            event, buffer = buffer.split("\n\n", 1)

                            for line in event.splitlines():
                                if not line.startswith("data:"):
                                    continue

                                raw = line[5:].strip()
                                if not raw:
                                    continue

                                try:
                                    tx = json.loads(raw)
                                except:
                                    continue

                                btc = float(tx.get("btc", 0))
                                txid = tx.get("txid")
                                flow = tx.get("flow")
                                exchange = tx.get("exchange") or "Unknown"

                                if not txid or btc <= 0:
                                    continue

                                send_alert = btc >= ALERT_WHALE_BTC

                                if btc >= MIN_WHALE_BTC:

                                    if flow == "DEPOSIT":
                                        emoji = "🔴"
                                        title = "SELL pressure"
                                        direction = "→ Exchange"
                                    elif flow == "WITHDRAWAL":
                                        emoji = "🟢"
                                        title = "ACCUMULATION"
                                        direction = "← Exchange"
                                    elif flow == "INTERNAL":
                                        emoji = "🟡"
                                        title = "Internal move"
                                        direction = "↔"
                                    else:
                                        emoji = "⚪"
                                        title = "OTC"
                                        direction = ""

                                    size = "HUGE" if btc >= 1000 else "Whale"

                                    msg = (
                                        f"{emoji} <b>{title}</b>\n"
                                        f"{size}: <b>{btc:.2f} BTC</b>\n"
                                        f"{direction} <b>{exchange}</b>\n"
                                        f"<code>{txid[:16]}…</code>"
                                    )

                                    for cid in list(subscribers):
                                        try:
                                            await bot.send_message(cid, msg)
                                        except:
                                            subscribers.discard(cid)

                                if send_alert:
                                    alert_msg = (
                                        f"⚡ <b>ALERT</b>\n"
                                        f"{flow or 'Unknown'}: <b>{btc:.2f} BTC</b>\n"
                                        f"<b>{exchange}</b>\n"
                                        f"<code>{txid[:16]}…</code>"
                                    )

                                    for cid in list(subscribers):
                                        try:
                                            await bot.send_message(cid, alert_msg)
                                        except:
                                            subscribers.discard(cid)

        except Exception as e:
            logger.error(f"SSE error: {e}")
            await asyncio.sleep(3)


async def main():
    asyncio.create_task(whale_listener())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())