import os
import time
import asyncio
import aiohttp
import json
import ssl
import certifi
from database.database import get_db
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
from aiogram.client.default import DefaultBotProperties

from config import Config
from logger import get_logger
from admin import setup_admin
from utils import calculate_system_stats
logger = get_logger(__name__)

BOT_TOKEN = Config.BOT_TOKEN
WEBAPP_URL = Config.WEBAPP_URL

# =====================================================
# API URL
# =====================================================

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

# =====================================================
# Bot init
# =====================================================

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()
setup_admin(dp)

subscribers = set()
seen_txids = set()  # защита от дублей


# =====================================================
# Start command
# =====================================================

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


# =====================================================
# SSE Listener
# =====================================================

async def whale_listener():
    await asyncio.sleep(2)
    logger.info("Starting whale_listener SSE task")

    buffer = ""

    try:
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    logger.info(f"[BOT] Connecting to {API}/events")
                    async with session.get(API + "/events", timeout=None, ssl=ssl_context) as resp:

                        logger.info("[BOT] Connected to SSE")
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

                                    txid = tx.get("txid")
                                    logger.info(f"[BOT] Received event {tx.get('txid')}")
                                    btc = float(tx.get("btc", 0))
                                    flow = tx.get("flow") or "UNKNOWN"
                                    from_cluster = tx.get("from_cluster")
                                    to_cluster = tx.get("to_cluster")

                                    if not txid or btc <= 0:
                                        continue

                                    # защита от повторной отправки
                                    if txid in seen_txids:
                                        continue
                                    seen_txids.add(txid)

                                    # -------------------------------------------------
                                    # Direction + Title
                                    # -------------------------------------------------

                                    if flow == "DEPOSIT":
                                        emoji = "🔴"
                                        title = "SELL pressure"
                                        direction = "→ Exchange"
                                    elif flow == "WITHDRAW":
                                        emoji = "🟢"
                                        title = "ACCUMULATION"
                                        direction = "← Exchange"
                                    elif flow == "INTERNAL":
                                        emoji = "🟡"
                                        title = "Internal move"
                                        direction = "↔ Internal"
                                    else:
                                        emoji = "⚪"
                                        title = "Unknown flow"
                                        direction = ""

                                    if btc >= 10000:
                                        size = "HUGE"
                                    else:
                                        size = "Whale"
                                
                                    msg = (
                                        f"{emoji} <b>{title}</b>\n"
                                        f"{size}: <b>{btc:.2f} BTC</b>\n"
                                        f"{direction}\n"
                                        f"<code>{txid[:16]}…</code>"
                                    )

                                    for cid in list(subscribers):
                                        try:
                                            logger.info(f"[BOT] Sending alert {txid} to {cid}")
                                            await bot.send_message(cid, msg)
                                        except Exception as e:
                                            logger.error(f"[BOT] Send error for {cid}: {e}")
                                            subscribers.discard(cid)

            except asyncio.CancelledError:
                logger.info("whale_listener cancelled")
                raise
            except Exception as e:
                logger.error(f"SSE error: {e}")
                await asyncio.sleep(3)

    except asyncio.CancelledError:
        logger.info("whale_listener stopped gracefully")
        
# ==============================================
# Price
# ==============================================
# ==============================================
# Price
# ==============================================
async def get_current_price():
    """
    Возвращает цену BTC.

    - В prod: берёт реальную цену через API (/price)
    - В dev/staging: возвращает mock-цену,
      которая плавно двигается вверх/вниз,
      чтобы trade_monitor корректно тестировался
    """

    # ===============================
    # DEV / STAGING → MOCK PRICE
    # ===============================
    if Config.ENV in ("dev", "stag"):
        base_price = 50000
        ts = int(time.time())
        cycle = ts % 120
    
        if cycle < 60:
            price = base_price + (cycle * 50)   # до +3000
        else:
            price = base_price + ((120 - cycle) * 50)
    
        return float(price)

    # ===============================
    # PROD → REAL PRICE
    # ===============================
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(API + "/price", ssl=ssl_context) as resp:
                if resp.status != 200:
                    return 0

                data = await resp.json()
                return float(data.get("price", 0))

    except Exception as e:
        logger.error(f"Price fetch error: {e}")
        return 0

# ==============================================
# Trade Monitor
# ==============================================
async def trade_monitor():
    await asyncio.sleep(5)

    while True:
        try:
            price = await get_current_price()
            if price <= 0:
                await asyncio.sleep(5)
                continue

            # --- 1️⃣ Получаем открытые сделки (READ BLOCK) ---
            conn = None
            try:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM trade_signals WHERE status='OPEN'")
                trades = c.fetchall()
            finally:
                if conn:
                    conn.close()

            # --- 2️⃣ Обрабатываем каждую сделку отдельно ---
            for trade in trades:
                direction = trade["direction"]
                entry = trade["entry"]
                stop = trade["stop"]
                take = trade["take"]
                position_size = trade["position_size"]
                trade_id = trade["id"]

                exit_price = None
                status = None

                if direction == "LONG":
                    if price >= take:
                        exit_price = take
                        status = "TP"
                    elif price <= stop:
                        exit_price = stop
                        status = "SL"

                if not exit_price:
                    continue

                pnl = (exit_price - entry) * position_size

                # --- 3️⃣ WRITE BLOCK (очень короткий) ---
                conn = None
                try:
                    conn = get_db()
                    c = conn.cursor()

                    # обновляем сделку
                    c.execute("""
                        UPDATE trade_signals
                        SET status=?, result=?
                        WHERE id=?
                    """, (status, pnl, trade_id))

                    # обновляем баланс
                    c.execute("SELECT balance FROM demo_account WHERE id=1")
                    balance = c.fetchone()["balance"]
                    new_balance = balance + pnl

                    c.execute("""
                        UPDATE demo_account
                        SET balance=?, updated_at=?
                        WHERE id=1
                    """, (new_balance, int(time.time())))

                    conn.commit()

                finally:
                    if conn:
                        conn.close()

                # --- 4️⃣ Только теперь отправляем сообщения ---
                msg = (
                    f"✅ <b>Сделка закрыта</b>\n"
                    f"Направление: {direction}\n"
                    f"Entry: {entry}\n"
                    f"Exit: {exit_price} ({status})\n"
                    f"Размер позиции: {position_size:.6f} BTC\n"
                    f"PnL: {pnl:+.2f} USDT\n"
                    f"Баланс: {new_balance:.2f} USDT"
                )

                for cid in list(subscribers):
                    try:
                        await bot.send_message(cid, msg)
                    except Exception as e:
                        logger.error(f"Send error for {cid}: {e}")
                        subscribers.discard(cid)

                # --- 5️⃣ Статистика (отдельный DB блок внутри функции) ---
                stats = calculate_system_stats()

                stats_msg = (
                    f"📊 <b>System Stats</b>\n\n"
                    f"Всего сделок: {stats['total_trades']}\n"
                    f"TP: {stats['wins']}\n"
                    f"SL: {stats['losses']}\n"
                    f"Winrate: {stats['winrate']}%\n\n"
                    f"💰 Total PnL: {stats['total_pnl']:+.2f} USDT\n"
                    f"💼 Баланс: {stats['balance']:.2f} USDT"
                )

                for cid in list(subscribers):
                    try:
                        await bot.send_message(cid, stats_msg)
                    except Exception as e:
                        logger.error(f"Send stats error for {cid}: {e}")
                        subscribers.discard(cid)

        except Exception as e:
            logger.error(f"Trade monitor error: {e}")

        await asyncio.sleep(5)
# ==============================================
# Hearbeat
# ==============================================
async def bot_heartbeat():
    while True:
        logger.info(f"[BOT] Alive. Subscribers: {len(subscribers)} Seen: {len(seen_txids)}")
        await asyncio.sleep(120)
# ==============================================
# Main
# ==============================================

async def main():
    listener_task = asyncio.create_task(whale_listener())
    heartbeat_task = asyncio.create_task(bot_heartbeat())
    print("BOT DB PATH:", Config.DB_PATH)
    monitor_task = asyncio.create_task(trade_monitor())
    try:
        await dp.start_polling(bot)
    finally:
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(main())