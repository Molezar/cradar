# services/price_fetcher.py
import time
import requests
import asyncio
from concurrent.futures import ThreadPoolExecutor
from logger import get_logger
from database.database import get_db

logger = get_logger(__name__)

# Кэш для хранения последней цены
_price_cache = {
    "price": None,
    "timestamp": 0,
    "source": None
}

# Резервные источники данных
PRICE_SOURCES = [
    {
        "name": "Binance",
        "url": "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
        "parser": lambda x: float(x["price"]),
        "timeout": 5
    },
    {
        "name": "Bybit",
        "url": "https://api.bybit.com/v5/market/tickers?category=spot&symbol=BTCUSDT",
        "parser": lambda x: float(x["result"]["list"][0]["lastPrice"]),
        "timeout": 5
    },
    {
        "name": "KuCoin",
        "url": "https://api.kucoin.com/api/v1/market/orderbook/level1?symbol=BTC-USDT",
        "parser": lambda x: float(x["data"]["price"]),
        "timeout": 5
    },
    {
        "name": "OKX",
        "url": "https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT",
        "parser": lambda x: float(x["data"][0]["last"]),
        "timeout": 5
    },
    {
        "name": "Coinbase",
        "url": "https://api.coinbase.com/v2/prices/BTC-USD/spot",
        "parser": lambda x: float(x["data"]["amount"]),
        "timeout": 5
    }
]

# ThreadPoolExecutor для синхронных запросов
_executor = ThreadPoolExecutor(max_workers=3)

def fetch_price_from_source(source):
    """Получает цену из одного источника (синхронно)"""
    try:
        response = requests.get(
            source["url"], 
            timeout=source["timeout"],
            headers={"User-Agent": "Mozilla/5.0"}
        )
        response.raise_for_status()
        data = response.json()
        price = source["parser"](data)
        
        if price and price > 0:
            logger.info(f"✅ Got price from {source['name']}: {price}")
            return price, source["name"]
    except Exception as e:
        logger.warning(f"❌ Failed to fetch from {source['name']}: {e}")
    
    return None, None

async def fetch_btc_price_async():
    """Асинхронно получает цену из всех источников параллельно"""
    loop = asyncio.get_event_loop()
    
    # Запускаем все запросы параллельно
    tasks = [
        loop.run_in_executor(_executor, fetch_price_from_source, source)
        for source in PRICE_SOURCES
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Собираем успешные результаты
    prices = []
    for result in results:
        if isinstance(result, Exception):
            continue
        price, source = result
        if price and price > 0:
            prices.append((price, source))
    
    return prices

def get_last_price_from_db():
    """Получает последнюю цену из БД"""
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT price FROM btc_price ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        if row and row["price"] > 0:
            return row["price"]
    except Exception as e:
        logger.error(f"Error reading price from DB: {e}")
    finally:
        if conn:
            conn.close()
    return None

async def get_best_price():
    """Получает наилучшую цену из всех доступных источников"""
    global _price_cache
    
    now = time.time()
    
    # Если кэш свежий (менее 10 секунд), возвращаем его
    if _price_cache["price"] and (now - _price_cache["timestamp"] < 10):
        return _price_cache["price"], _price_cache["source"]
    
    # Пробуем получить свежие цены
    prices = await fetch_btc_price_async()
    
    if prices:
        # Берем среднее значение от всех успешных источников
        avg_price = sum(p[0] for p in prices) / len(prices)
        sources = [p[1] for p in prices]
        
        # Обновляем кэш
        _price_cache.update({
            "price": avg_price,
            "timestamp": now,
            "source": f"average from {', '.join(sources)}"
        })
        
        logger.info(f"💰 Average price: {avg_price} from {len(prices)} sources")
        return avg_price, _price_cache["source"]
    
    # Если нет свежих цен, пробуем БД
    db_price = get_last_price_from_db()
    if db_price and db_price > 0:
        logger.warning(f"⚠️ Using stale price from DB: {db_price}")
        _price_cache.update({
            "price": db_price,
            "timestamp": now,
            "source": "database (stale)"
        })
        return db_price, "database"
    
    # Если ничего нет, возвращаем кэш даже если старый
    if _price_cache["price"]:
        logger.error(f"🔴 CRITICAL: Using very stale price from cache: {_price_cache['price']}")
        return _price_cache["price"], "cache (very stale)"
    
    return 0, None

def update_price_sampler_with_fallback():
    """Обновляет price_sampler в server.py для использования нескольких источников"""
    pass  # Это будет использовано в следующем шаге