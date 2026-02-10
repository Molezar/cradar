import os

ENV = os.getenv("ENV", "dev")
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL", "http://localhost:8000")

DEBUG = ENV == "dev"
IS_PROD = ENV == "prod"