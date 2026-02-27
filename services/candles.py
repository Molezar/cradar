# services/candles.py
import aiohttp
from services.api_config import API, ssl_context

async def get_candles(limit=100):
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{API}/candles?limit={limit}",
            ssl=ssl_context
        ) as resp:
            if resp.status != 200:
                return []

            return await resp.json()