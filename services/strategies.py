#services/strategies.py
from services.signal_engine import collect_indicators, aggregate_signals
from services.risk_engine import build_trade
from services.price import get_current_price
from services.market_data import get_market_candles
from logger import get_logger

logger = get_logger(__name__)

class BaseStrategy:
    def __init__(self, max_leverage=5, min_threshold=0.2):
        self.max_leverage = max_leverage
        self.min_threshold = min_threshold

    async def generate_signal(self):
        price = await get_current_price()
        if price == 0:
            return None
        
        candles = await get_market_candles(limit=100)

        if not candles or len(candles) < 50:
            logger.warning("Not enough candles")
            return None
        
        indicators = collect_indicators(candles)
        logger.info(f"Indicators: {[s.name for s in indicators]}")

        aggregated = aggregate_signals(indicators)
        if aggregated is None or abs(aggregated["score"]) < self.min_threshold:
            return None

        # Передаём max_leverage для динамического расчета
        return build_trade(aggregated, price, base_leverage=self.max_leverage)

class AggressiveStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(max_leverage=5, min_threshold=0.02)


class ConservativeStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(max_leverage=3, min_threshold=0.25)