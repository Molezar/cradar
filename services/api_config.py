#services/api_config.py
import os
import ssl
import certifi
from config import Config

if Config.IS_PROD:
    API = os.getenv("API_URL")
    if not API:
        raise ValueError("API_URL env variable is missing on PROD!")
    ssl_context = ssl.create_default_context(cafile=certifi.where())
else:
    API = "http://127.0.0.1:" + os.environ.get("PORT", "8000")
    ssl_context = None