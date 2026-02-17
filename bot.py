import os
import asyncio
import aiohttp
import json
import sqlite3
import time

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


# ========================================
# Whale flow listener
# ========================================

async def whale_listener():
    await asyncio.sleep(2)
    logger.info("Starting whale_listener SSE task")

    buffer = ""

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(API + "/events", timeout=None) as resp:
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
                                exchange = tx.get("exchange")

                                if not txid or btc <= 0:
                                    continue

                                # -----------------------------
                                # Alert logic
                                # -----------------------------
                                send_alert = btc >= ALERT_WHALE_BTC
                                alert_msg = None

                                if send_alert:
                                    # Попробуем подтянуть биржу и направление из БД
                                    try:
                                        db = sqlite3.connect(Config.DB_PATH)
                                        db.row_factory = sqlite3.Row
                                        c = db.cursor()
                                        r = c.execute("""
                                            SELECT flow_type, exchange FROM whale_classification
                                            WHERE txid = ?
                                        """, (txid,)).fetchone()
                                        db.close()

                                        if r:
                                            flow_known = r["flow_type"]
                                            exchange_known = r["exchange"] or "Unknown"
                                            alert_msg = (
                                                f"⚡ <b>ALERT</b>\n"
                                                f"{flow_known}: <b>{btc:.2f} BTC</b>\n"
                                                f"{'→' if flow_known=='DEPOSIT' else '←' if flow_known=='WITHDRAWAL' else '↔'} "
                                                f"<b>{exchange_known}</b>\n"
                                                f"<code>{txid[:16]}…</code>"
                                            )
                                        else:
                                            alert_msg = (
                                                f"⚡ <b>ALERT</b>\n"
                                                f"<b>{btc:.2f} BTC</b>\n"
                                                f"<code>{txid[:16]}…</code>"
                                            )

                                    except Exception as e:
                                        logger.exception(f"Alert DB lookup error: {e}")
                                        alert_msg = (
                                            f"⚡ <b>ALERT</b>\n"
                                            f"<b>{btc:.2f} BTC</b>\n"
                                            f"<code>{txid[:16]}…</code>"
                                        )

                                # -----------------------------
                                # Normal whale message logic (MIN_WHALE_BTC)
                                # -----------------------------
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
                                        f"{direction} <b>{exchange or 'Unknown'}</b>\n"
                                        f"<code>{txid[:16]}…</code>"
                                    )

                                    logger.info(f"{flow} {btc} BTC {exchange}")

                                    for cid in list(subscribers):
                                        try:
                                            await bot.send_message(cid, msg)
                                        except:
                                            subscribers.discard(cid)

                                # -----------------------------
                                # Send alert if needed
                                # -----------------------------
                                if send_alert and alert_msg:
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