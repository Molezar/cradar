# services/indicators/prediction.py
import aiohttp
from services.api_config import API
from services.indicators.base import IndicatorSignal
from logger import get_logger

logger = get_logger(__name__)

async def get_prediction_signal(price):

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API}/prediction") as resp:
            if resp.status != 200:
                return IndicatorSignal("Prediction", "NEUTRAL", 0, 0)

            data = await resp.json()

    best_pct = None

    for w, v in data.items():
        pct = float(v.get("pct", 0))
        if best_pct is None or abs(pct) > abs(best_pct):
            best_pct = pct

    if best_pct is None or abs(best_pct) < 0.001:
        return IndicatorSignal("Prediction", "NEUTRAL", 0, 0)

    direction = "LONG" if best_pct > 0 else "SHORT"

    return IndicatorSignal(
        "Prediction",
        direction,
        strength=min(abs(best_pct), 1),
        confidence=0.7
    )