# services/indicators/base.py
class IndicatorSignal:
    def __init__(self, name, direction, strength, confidence, meta=None):
        self.name = name
        self.direction = direction  # LONG / SHORT / NEUTRAL
        self.strength = strength    # 0.0 - 1.0
        self.confidence = confidence  # 0.0 - 1.0
        self.meta = meta or {}

    def score(self):
        if self.direction == "LONG":
            return self.strength * self.confidence
        elif self.direction == "SHORT":
            return -self.strength * self.confidence
        return 0