# config.py
from dotenv import load_dotenv
import os
from pathlib import Path

load_dotenv()

class Config:
    ENV = os.getenv("ENV", "DEV").upper()
    
    if ENV == "PROD":
        DB_PATH = Path("/data/radar_prod.db")
    elif ENV == "STAG":
        DB_PATH = Path("/data/radar_stag.db")
    else:
        DB_PATH = Path("database/radar.db")

    BOT_TOKEN = os.getenv("BOT_TOKEN")
    ADMIN_ID = int(os.getenv("ADMIN_TELEGRAM_ID", 0))
    WEBAPP_URL = os.getenv("WEBAPP_URL")
    API_URL = os.getenv("API_URL")

    MIN_WHALE_BTC = float(os.getenv("MIN_WHALE_BTC", "50"))
    ALERT_WHALE_BTC = float(os.getenv("ALERT_WHALE_BTC", "1000"))
    
    USE_API_CANDLES = True
    
    DEBUG = ENV == "DEV"
    IS_PROD = ENV == "PROD"