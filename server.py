from flask import Flask, jsonify, send_from_directory
from onchain import btc_inflow_last_minutes
import os
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Папка с MiniApp
MINIAPP_DIR = os.path.join(os.path.dirname(__file__), "miniapp")

# -----------------------
# Настройка режима работы
# -----------------------
# test_mode = True  -> MiniApp получает случайные значения inflow (для тестов и разработки)
# test_mode = False -> MiniApp получает реальные данные с Binance через Blockstream
TEST_MODE = True  # <- сейчас включен тестовый режим, чтобы всегда видеть inflow и отлаживать MiniApp

@app.route("/data")
def get_data():
    # Вызов функции с указанием режима и периода (в минутах)
    inflow = btc_inflow_last_minutes(minutes=60, test_mode=TEST_MODE)
    return jsonify({"btc_inflow": inflow})

@app.route("/")
def miniapp_index():
    # Отдаём index.html
    return send_from_directory(MINIAPP_DIR, "index.html")

@app.route("/<path:path>")
def miniapp_files(path):
    # Отдаём остальные файлы MiniApp (JS, CSS)
    return send_from_directory(MINIAPP_DIR, path)

if __name__ == "__main__":
    # Запуск сервера на всех интерфейсах и порту 8000
    app.run(host="0.0.0.0", port=8000)