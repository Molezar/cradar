import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# Определяем окружение
ENV = os.getenv("ENV", "DEV")  # DEV локально, PROD/STAG на Railway

# === Цветной форматтер (только для DEV) ===
class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[97m",   # белый
        logging.INFO: "\033[32m",    # зелёный
        logging.WARNING: "\033[33m", # жёлтый
        logging.ERROR: "\033[31m",   # красный
        logging.CRITICAL: "\033[41m" # красный фон
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelno, self.RESET)
        message = super().format(record)
        return f"{color}{message}{self.RESET}"

# === Формат логов ===
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Получаем root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.handlers = []  # очищаем старые хендлеры

if ENV in ("PROD", "STAG"):
    # === Продакшен / Стад — stdout/stderr ===
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.addFilter(lambda record: record.levelno < logging.ERROR)
    stdout_handler.setFormatter(ColorFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)
    stderr_handler.setFormatter(log_formatter)

    root_logger.addHandler(stdout_handler)
    root_logger.addHandler(stderr_handler)

else:
    # === DEV — файл + цветная консоль ===
    os.makedirs("logs", exist_ok=True)

    file_handler = RotatingFileHandler(
        "logs/bot.log", maxBytes=5*1024*1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(log_formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(ColorFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

# === Функция для получения логгера ===
def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
    
if __name__ == "__main__":
    log = get_logger("TestLogger")

    log.debug("🔵 DEBUG message — проверка цвета")
    log.info("🟢 INFO message — проверка цвета")
    log.warning("🟠 WARNING message — проверка цвета")
    log.error("🔴 ERROR message — проверка цвета")
    log.critical("⚫ CRITICAL message — проверка цвета")
    try:
        1 / 0
    except Exception:
        log.exception("💥 EXCEPTION message — проверка цвета")