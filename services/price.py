# services/price.py
import aiohttp
import asyncio
from services.api_config import API, ssl_context
from logger import get_logger
from services.price_fetcher import get_best_price

logger = get_logger(__name__)

# Локальный кэш для быстрого доступа
_price_cache = {
    "price": 0,
    "timestamp": 0
}

async def get_current_price(force_refresh=False):
    """
    Получает текущую цену BTC.
    Сначала пробует через локальный API, затем через прямые источники.
    """
    global _price_cache
    
    now = asyncio.get_event_loop().time()
    
    # Если кэш свежий и не требуем принудительного обновления
    if not force_refresh and _price_cache["price"] > 0 and (now - _price_cache["timestamp"] < 5):
        return _price_cache["price"]
    
    # Пробуем получить цену через локальный API
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API}/price", ssl=ssl_context, timeout=3) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    price = float(data.get("price", 0))
                    if price > 0:
                        _price_cache.update({
                            "price": price,
                            "timestamp": now
                        })
                        return price
    except Exception as e:
        logger.debug(f"Local API price fetch failed: {e}")
    
    # Если локальный API не сработал, используем прямые источники
    logger.info("Falling back to direct price sources...")
    price, source = await get_best_price()
    
    if price > 0:
        _price_cache.update({
            "price": price,
            "timestamp": now
        })
        logger.info(f"Got price from {source}: {price}")
        return price
    
    # Если ничего не сработало, возвращаем последний известный кэш
    if _price_cache["price"] > 0:
        logger.warning(f"Using stale cached price: {_price_cache['price']}")
        return _price_cache["price"]
    
    return 0

async def force_refresh_price():
    """Принудительно обновляет цену"""
    return await get_current_price(force_refresh=True)