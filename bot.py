#bot.py
import time
import asyncio
import aiohttp
import json

from database.database import get_db
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from config import Config
from logger import get_logger
from admin import setup_admin
from utils import calculate_system_stats
from services.price import get_current_price
from services.api_config import API, ssl_context
from admin.signal.callbacks import get_auto_mode
from admin.signal.callbacks import handle_signal

logger = get_logger(__name__)

BOT_TOKEN = Config.BOT_TOKEN
WEBAPP_URL = Config.WEBAPP_URL

MIN_WHALE_BTC = Config.MIN_WHALE_BTC
ALERT_WHALE_BTC = Config.ALERT_WHALE_BTC

# ==============================================
# Bot init
# ==============================================

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
subscribers = set()
seen_txids = set()  # защита от дублей

dp = Dispatcher()
setup_admin(dp, subscribers)

# ==============================================
# SSE Listener
# ==============================================
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
# Trade Monitor
# ==============================================
  async def trade_monitor():
    await asyncio.sleep(5)
    logger.info("Trade monitor starting...")
    logger.info(f"get_db in globals: {'get_db' in globals()}")

    while True:
        closed_any_trade = False  # 🔥 флаг закрытия сделки

        try:
            price = await get_current_price()
            if price <= 0:
                await asyncio.sleep(5)
                continue

            # --- 1️⃣ READ BLOCK ---
            conn = None
            try:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM trade_signals WHERE status='OPEN'")
                trades = c.fetchall()
            finally:
                if conn:
                    conn.close()

            # --- 2️⃣ Обрабатываем сделки ---
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

                # если условия не выполнены
                if exit_price is None:
                    continue

                pnl = (exit_price - entry) * position_size

                # --- 3️⃣ WRITE BLOCK ---
                conn = None
                try:
                    conn = get_db()
                    c = conn.cursor()

                    # защита от двойного закрытия
                    c.execute("""
                        UPDATE trade_signals
                        SET status=?, result=?
                        WHERE id=? AND status='OPEN'
                    """, (status, pnl, trade_id))

                    # если сделка уже закрыта другой корутиной
                    if c.rowcount == 0:
                        conn.rollback()
                        continue

                    # безопасное обновление баланса
                    c.execute("""
                        UPDATE demo_account
                        SET balance = balance + ?,
                            updated_at=?
                        WHERE id=1
                    """, (pnl, int(time.time())))

                    # получаем новый баланс
                    c.execute("SELECT balance FROM demo_account WHERE id=1")
                    new_balance = c.fetchone()["balance"]

                    conn.commit()
                    closed_any_trade = True

                finally:
                    if conn:
                        conn.close()

                # --- 4️⃣ Отправка сообщений ---
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

                # --- 5️⃣ Статистика ---
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

        # --- 6️⃣ AUTO режим только если реально закрылась сделка ---
        if get_auto_mode() and closed_any_trade and subscribers:

            class FakeCallback:
                def __init__(self, bot, cid):
                    self.message = type("obj", (), {"chat": type("obj", (), {"id": cid})})
                    self.from_user = type("obj", (), {"id": cid})
                    self.bot = bot

                async def answer(self):
                    pass

            # создаём один новый сигнал, а не по количеству подписчиков
            cid = next(iter(subscribers))

            try:
                fake = FakeCallback(bot, cid)
                await handle_signal(fake)
            except Exception as e:
                logger.error(f"AUTO signal error: {e}")

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
    logger.info("Polling starting...")
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