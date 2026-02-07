from flask import Flask, jsonify, send_from_directory, request
from onchain import btc_inflow_last_minutes
import os
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

MINIAPP_DIR = os.path.join(os.path.dirname(__file__), "miniapp")

# -----------------------
# Настройки по умолчанию
# -----------------------
TEST_MODE = False       # True = тестовые данные, False = реальные
MINUTES_DEFAULT = 360   # 6 часов

@app.route("/data")
def get_data():
    # Можно через GET менять режим и минуты, пример: ?test=1&minutes=1440
    test_mode = request.args.get("test", str(int(TEST_MODE))) == "1"
    minutes = int(request.args.get("minutes", MINUTES_DEFAULT))
    inflow = btc_inflow_last_minutes(minutes=minutes, test_mode=test_mode)
    return jsonify({"btc_inflow": inflow})

@app.route("/")
def miniapp_index():
    return send_from_directory(MINIAPP_DIR, "index.html")

@app.route("/<path:path>")
def miniapp_files(path):
    return send_from_directory(MINIAPP_DIR, path)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)