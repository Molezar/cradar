import aiohttp
from services.api_config import API, ssl_context
from logger import get_logger

logger = get_logger(__name__)


async def get_current_price():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API}/price", ssl=ssl_context) as resp:
                if resp.status != 200:
                    logger.error(f"Price API returned status {resp.status}")
                    return 0

                data = await resp.json()
                return float(data.get("price", 0))

    except Exception as e:
        logger.error(f"Price fetch error: {e}")
        return 0