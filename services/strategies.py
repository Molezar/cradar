from services.signal_engine import collect_indicators, aggregate_signals
from services.risk_engine import build_trade
from services.price import get_current_price
from logger import get_logger

logger = get_logger(__name__)

class BaseStrategy:

    async def generate_signal(self):

        price = await get_current_price()
        if price == 0:
            return None

        indicators = await collect_indicators(price)
        logger.info(f"Indicators: {[s.name for s in indicators]}")
        
        aggregated = aggregate_signals(indicators)

        if aggregated is None:
            return None

        return build_trade(aggregated, price)


class AggressiveStrategy(BaseStrategy):
    pass


class ConservativeStrategy(BaseStrategy):
    pass