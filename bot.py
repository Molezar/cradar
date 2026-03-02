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
        closed_any_trade = False

        try:
            price = await get_current_price()
            if price <= 0:
                await asyncio.sleep(5)
                continue

            # =============================
            # 1️⃣ READ OPEN TRADES
            # =============================
            conn = None
            try:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM trade_signals WHERE status='OPEN'")
                trades = c.fetchall()
            finally:
                if conn:
                    conn.close()

            # =============================
            # 2️⃣ PROCESS TRADES
            # =============================
            for trade in trades:
                direction = trade["direction"]
                entry = trade["entry"]
                stop = trade["stop"]
                take = trade["take"]
                position_size = trade["position_size"]
                trade_id = trade["id"]

                exit_price = None
                status = None

                # ----- LONG -----
                if direction == "LONG":
                    if price >= take:
                        exit_price = take
                        status = "TP"
                    elif price <= stop:
                        exit_price = stop
                        status = "SL"

                # ----- SHORT -----
                elif direction == "SHORT":
                    if price <= take:
                        exit_price = take
                        status = "TP"
                    elif price >= stop:
                        exit_price = stop
                        status = "SL"

                if exit_price is None:
                    continue

                # ----- PnL -----
                if direction == "LONG":
                    pnl = (exit_price - entry) * position_size
                else:
                    pnl = (entry - exit_price) * position_size

                # =============================
                # 3️⃣ WRITE BLOCK (ATOMIC)
                # =============================
                conn = None
                try:
                    conn = get_db()
                    c = conn.cursor()

                    c.execute("""
                        UPDATE trade_signals
                        SET status=?, result=?
                        WHERE id=? AND status='OPEN'
                    """, (status, pnl, trade_id))

                    if c.rowcount == 0:
                        conn.rollback()
                        continue

                    c.execute("""
                        UPDATE demo_account
                        SET balance = balance + ?,
                            updated_at=?
                        WHERE id=1
                    """, (pnl, int(time.time())))

                    conn.commit()
                    closed_any_trade = True

                except Exception:
                    if conn:
                        conn.rollback()
                    raise
                finally:
                    if conn:
                        conn.close()

                # =============================
                # 4️⃣ SEND MESSAGE
                # =============================
                percent = (
                    (pnl / (entry * position_size)) * 100
                    if entry * position_size != 0 else 0
                )

                emoji = "🟢" if pnl > 0 else "🔴"

                stats = calculate_system_stats()

                msg = (
                    f"{emoji} <b>Сделка закрыта ({status})</b>\n\n"

                    f"📌 Направление: <b>{direction}</b>\n"
                    f"💰 Entry: <b>{entry}</b>\n"
                    f"💵 Exit: <b>{exit_price}</b>\n"
                    f"📦 Размер: <b>{position_size:.6f} BTC</b>\n\n"

                    f"💎 PnL: <b>{pnl:+.2f} USDT</b>\n"
                    f"📊 Доходность: <b>{percent:+.2f}%</b>\n"
                    f"💼 Баланс: <b>{stats['balance']:.2f} USDT</b>\n\n"

                    f"━━━━━━━━━━━━━━\n"
                    f"📊 <b>System Stats</b>\n"
                    f"Всего сделок: {stats['total_trades']}\n"
                    f"TP: {stats['wins']} | SL: {stats['losses']}\n"
                    f"Winrate: {stats['winrate']}%\n"
                    f"💰 Total PnL: {stats['total_pnl']:+.2f} USDT"
                )

                for cid in list(subscribers):
                    try:
                        await bot.send_message(cid, msg)
                    except Exception as e:
                        logger.error(f"Send error for {cid}: {e}")
                        subscribers.discard(cid)

        except Exception as e:
            logger.error(f"Trade monitor error: {e}")

        # =============================
        # 5️⃣ AUTO MODE (SAFE)
        # =============================
        if get_auto_mode() and closed_any_trade and subscribers:

            conn = None
            try:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT COUNT(*) as cnt FROM trade_signals WHERE status='OPEN'")
                open_count = c.fetchone()["cnt"]
            finally:
                if conn:
                    conn.close()

            if open_count == 0:

                class FakeCallback:
                    def __init__(self, bot, cid):
                        self.message = type("obj", (), {"chat": type("obj", (), {"id": cid})})
                        self.from_user = type("obj", (), {"id": cid})
                        self.bot = bot

                    async def answer(self):
                        pass

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