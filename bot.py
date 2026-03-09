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
from admin.signal.callbacks import (
    get_auto_mode,
    generate_and_save_signal,
    handle_signal
)

logger = get_logger(__name__)

BOT_TOKEN = Config.BOT_TOKEN
WEBAPP_URL = Config.WEBAPP_URL

MIN_WHALE_BTC = Config.MIN_WHALE_BTC
ALERT_WHALE_BTC = Config.ALERT_WHALE_BTC

NET_ALERT_THRESHOLD = 500          # порог в BTC, при превышении которого шлём алерт
NET_ALERT_INTERVAL = 1800           # проверка раз в 30 минут (1800 секунд)
NET_ALERT_COOLDOWN = 3600           # минимальное время между повторными алертами (1 час)

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
# Функции для мониторинга свечей
# ==============================================
async def get_candle_info():
    """Получает информацию о последних свечах из БД"""
    conn = None
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Получаем последнюю свечу
        row = c.execute("""
            SELECT open_time, open, high, low, close, volume
            FROM btc_candles_1m
            ORDER BY open_time DESC
            LIMIT 1
        """).fetchone()
        
        if not row:
            return None
            
        candle = dict(row)
        candle_time = time.strftime('%H:%M:%S', time.localtime(candle['open_time']))
        current_time = int(time.time())
        time_diff = current_time - candle['open_time']
        
        return {
            "time": candle_time,
            "open": candle['open'],
            "high": candle['high'],
            "low": candle['low'],
            "close": candle['close'],
            "volume": candle['volume'],
            "age": time_diff,
            "is_fresh": time_diff < 90
        }
        
    except Exception as e:
        logger.error(f"Error getting candle info: {e}")
        return None
    finally:
        if conn:
            conn.close()

async def check_candles_api():
    """Проверяет доступность API свечей напрямую"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": "BTCUSDT", "interval": "1m", "limit": 1},
                timeout=5
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and len(data) > 0:
                        return True, float(data[0][4])
                return False, None
    except Exception as e:
        logger.debug(f"Candles API check failed: {e}")
        return False, None
        
# ==============================================
# SSE Listeners
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
                                    btc = float(tx.get("btc", 0))
                                    flow = tx.get("flow_type") or "UNKNOWN"
                                    confidence = float(tx.get("confidence", 0.7))
                                    from_cluster = tx.get("from_cluster")
                                    to_cluster = tx.get("to_cluster")

                                    if not txid or btc <= 0:
                                        continue

                                    # защита от повторной отправки
                                    if txid in seen_txids:
                                        continue
                                    seen_txids.add(txid)

                                    # -------------------------------------------------
                                    # Слать алерт только для верных транзакций
                                    # -------------------------------------------------
                                    if btc >= ALERT_WHALE_BTC and flow != "UNKNOWN" and confidence >= 0.7:

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

                                        # Размер
                                        size = "HUGE" if btc >= 10000 else "Whale"

                                        msg = (
                                            f"{emoji} <b>{title}</b>\n"
                                            f"{size}: <b>{btc:.2f} BTC</b>\n"
                                            f"Confidence: <b>{confidence*100:.0f}%</b>\n"
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

async def netflow_alert_monitor():
    """Мониторит чистый поток (withdraw - deposit) за последний час и шлёт алерты при значительных отклонениях."""
    await asyncio.sleep(10)
    logger.info("Starting netflow alert monitor")

    last_alert_time = 0
    last_alert_sign = None

    while True:
        try:
            now = int(time.time())
            since = now - 3600  # последний час

            conn = None
            try:
                conn = get_db()
                c = conn.cursor()

                # Сумма DEPOSIT за последний час
                c.execute("""
                    SELECT COALESCE(SUM(btc), 0) as total
                    FROM whale_classification
                    WHERE time > ? AND flow_type = 'DEPOSIT'
                """, (since,))
                deposit = c.fetchone()["total"]

                # Сумма WITHDRAW за последний час
                c.execute("""
                    SELECT COALESCE(SUM(btc), 0) as total
                    FROM whale_classification
                    WHERE time > ? AND flow_type = 'WITHDRAW'
                """, (since,))
                withdraw = c.fetchone()["total"]

                net = withdraw - deposit
                logger.debug(f"netflow check: net={net:.2f} BTC")

                abs_net = abs(net)
                if abs_net >= NET_ALERT_THRESHOLD:
                    current_time = time.time()
                    current_sign = 'positive' if net > 0 else 'negative'

                    time_condition = (current_time - last_alert_time) > NET_ALERT_COOLDOWN
                    sign_changed = (last_alert_sign is not None and last_alert_sign != current_sign)

                    if time_condition or sign_changed:
                        emoji = "🔴" if net < 0 else "🟢"
                        direction = "приток на биржи (давление вниз)" if net < 0 else "отток с бирж (накопление)"

                        msg = (
                            f"{emoji} <b>Чистый поток за последний час</b>\n"
                            f"💰 <b>{abs_net:.2f} BTC</b> {direction}\n\n"
                            f"📥 DEPOSIT: {deposit:.2f} BTC\n"
                            f"📤 WITHDRAW: {withdraw:.2f} BTC\n"
                            f"📊 NET: {net:+.2f} BTC"
                        )

                        for cid in list(subscribers):
                            try:
                                await bot.send_message(cid, msg)
                                logger.info(f"Netflow alert sent to {cid}: net={net:.2f}")
                            except Exception as e:
                                logger.error(f"Send error for {cid}: {e}")
                                subscribers.discard(cid)

                        last_alert_time = current_time
                        last_alert_sign = current_sign

            except Exception as e:
                logger.exception(f"Database error in netflow_alert_monitor: {e}")
            finally:
                if conn:
                    conn.close()

        except Exception as e:
            logger.exception(f"Error in netflow_alert_monitor: {e}")

        await asyncio.sleep(NET_ALERT_INTERVAL)
        
# ==============================================
# Trade Monitor
# ==============================================
async def trade_monitor():
    await asyncio.sleep(5)
    logger.info("🚀 Trade monitor starting with enhanced price fallback...")
    
    # Статистика для мониторинга
    last_valid_price = 0
    price_failures = 0
    last_price_log = 0

    while True:
        closed_any_trade = False

        try:
            # Пытаемся получить цену с принудительным обновлением если долго нет данных
            price = await get_current_price(force_refresh=(price_failures > 3))
            
            current_time = time.time()
            
            # Логируем цену каждые 60 секунд
            if current_time - last_price_log > 60:
                if price > 0:
                    logger.info(f"📊 Current price: {price}")
                    last_price_log = current_time
                else:
                    logger.warning(f"⚠️ No valid price available (failure #{price_failures})")
            
            if price <= 0:
                price_failures += 1
                
                # Если долго нет цены, используем последнюю известную из кэша
                if price_failures > 3 and last_valid_price > 0:
                    logger.warning(f"Using last known price: {last_valid_price} (after {price_failures} failures)")
                    price = last_valid_price
                else:
                    await asyncio.sleep(5)
                    continue
            else:
                # Сброс счетчика ошибок и обновление последней цены
                price_failures = 0
                last_valid_price = price

            # =============================
            # 1️⃣ READ OPEN TRADES
            # =============================
            conn = None
            try:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM trade_signals WHERE status='OPEN'")
                trades = c.fetchall()
                
                if trades:
                    logger.info(f"Found {len(trades)} open trades, current price: {price}")
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
                        logger.info(f"🎯 LONG TP triggered: price={price:.2f} >= take={take:.2f}")
                    elif price <= stop:
                        exit_price = stop
                        status = "SL"
                        logger.info(f"🛑 LONG SL triggered: price={price:.2f} <= stop={stop:.2f}")

                # ----- SHORT -----
                elif direction == "SHORT":
                    if price <= take:
                        exit_price = take
                        status = "TP"
                        logger.info(f"🎯 SHORT TP triggered: price={price:.2f} <= take={take:.2f}")
                    elif price >= stop:
                        exit_price = stop
                        status = "SL"
                        logger.info(f"🛑 SHORT SL triggered: price={price:.2f} >= stop={stop:.2f}")

                if exit_price is None:
                    continue

                # ----- PnL Calculation -----
                if direction == "LONG":
                    pnl = (exit_price - entry) * position_size
                else:
                    pnl = (entry - exit_price) * position_size

                # =============================
                # 3️⃣ CLOSE TRADE (ATOMIC)
                # =============================
                conn = None
                try:
                    conn = get_db()
                    c = conn.cursor()

                    # Проверяем, что сделка все еще открыта
                    c.execute("""
                        UPDATE trade_signals
                        SET status=?, result=?
                        WHERE id=? AND status='OPEN'
                    """, (status, pnl, trade_id))

                    if c.rowcount == 0:
                        logger.warning(f"Trade {trade_id} was already closed")
                        conn.rollback()
                        continue

                    # Обновляем баланс
                    c.execute("""
                        UPDATE demo_account
                        SET balance = balance + ?,
                            updated_at=?
                        WHERE id=1
                    """, (pnl, int(time.time())))

                    conn.commit()
                    closed_any_trade = True
                    
                    logger.info(f"✅ Trade {trade_id} closed: {status} with PnL {pnl:+.2f} USDT")

                except Exception as e:
                    logger.error(f"Error closing trade {trade_id}: {e}")
                    if conn:
                        conn.rollback()
                    continue
                finally:
                    if conn:
                        conn.close()

                # =============================
                # 4️⃣ SEND NOTIFICATION
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
                    f"💰 Entry: <b>{entry:.2f}</b>\n"
                    f"💵 Exit: <b>{exit_price:.2f}</b>\n"
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
                        logger.info(f"Closed trade notification sent to {cid}")
                    except Exception as e:
                        logger.error(f"Send error for {cid}: {e}")
                        subscribers.discard(cid)

        except Exception as e:
            logger.exception(f"Critical error in trade monitor: {e}")

        # =============================
        # 5️⃣ AUTO MODE (SAFE)
        # =============================
        if get_auto_mode() and closed_any_trade and subscribers:
            try:
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
                    logger.info("Auto mode: generating new signal...")
                    result = await generate_and_save_signal()
                    
                    if isinstance(result, dict):
                        text = (
                            f"🤖 <b>AUTO SIGNAL</b>\n\n"
                            f"🎯 {result['direction']}\n"
                            f"📍 Entry: {result['entry']:.2f}\n"
                            f"🛑 Stop: {result['stop']:.2f}\n"
                            f"🎯 Take: {result['take']:.2f}\n"
                            f"💰 Size: {result['position_size']:.6f} BTC"
                        )
                    
                        for cid in list(subscribers):
                            try:
                                await bot.send_message(cid, text)
                                logger.info(f"Auto signal sent to {cid}")
                            except Exception as e:
                                logger.error(f"Auto signal send error: {e}")
                                subscribers.discard(cid)
            except Exception as e:
                logger.error(f"Auto mode error: {e}")

        await asyncio.sleep(5)
 
# ==============================================
# Hearbeat
# ==============================================
async def bot_heartbeat():
    while True:
        try:
            # Получаем текущую цену
            price = await get_current_price()
            price_status = "✅" if price > 0 else "❌"
            
            # Получаем информацию о свечах
            candle = await get_candle_info()
            candles_api_ok, api_price = await check_candles_api()
            
            # Формируем статус свечей
            if candle:
                age_status = "✅" if candle["is_fresh"] else "⚠️" if candle["age"] < 300 else "❌"
                
                # Проверка консистентности с текущей ценой
                if price > 0:
                    diff = abs(price - candle["close"]) / price * 100
                    consistency = "✅" if diff < 1 else "⚠️" if diff < 3 else "❌"
                else:
                    consistency = "❓"
                
                candle_log = (
                    f"\n📊 CANDLE: {candle['time']}"
                    f"\n  O:{candle['open']:.0f} H:{candle['high']:.0f} L:{candle['low']:.0f} C:{candle['close']:.0f}"
                    f"\n  Vol:{candle['volume']:.2f} BTC | Age:{candle['age']}s {age_status}"
                    f"\n  Consistency:{consistency} | API:{'✅' if candles_api_ok else '❌'}"
                )
                
                # Если есть расхождение с API
                if candles_api_ok and api_price and abs(api_price - candle['close']) / api_price * 100 > 1:
                    candle_log += f"\n  ⚠️ API diff: {abs(api_price - candle['close']):.2f}"
            else:
                candle_log = "\n📊 CANDLE: ❌ No data"
            
            # Логируем
            logger.info(
                f"[BOT] Alive. Subs:{len(subscribers)} Seen:{len(seen_txids)} "
                f"Price:{price_status} {price if price > 0 else 'N/A'}"
                f"{candle_log}"
            )
            
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
            
        await asyncio.sleep(120)
        
# ==============================================
# Main
# ==============================================
async def main():
    listener_task = asyncio.create_task(whale_listener())
    heartbeat_task = asyncio.create_task(bot_heartbeat())
    monitor_task = asyncio.create_task(trade_monitor())
    netflow_task = asyncio.create_task(netflow_alert_monitor())   # <-- добавить
    
    print("BOT DB PATH:", Config.DB_PATH)
    logger.info("Polling starting...")
    try:
        await dp.start_polling(bot)
    finally:
        listener_task.cancel()
        netflow_task.cancel()   # и здесь отменить
        try:
            await listener_task
            await netflow_task
        except asyncio.CancelledError:
            pass
        
if __name__ == "__main__":
    asyncio.run(main())