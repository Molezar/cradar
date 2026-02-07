from flask import Flask, jsonify, send_from_directory
from onchain import btc_inflow_last_minutes
import os
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

MINIAPP_DIR = os.path.join(os.path.dirname(__file__), "miniapp")

# -----------------------
# ГЛАВНЫЕ НАСТРОЙКИ
# -----------------------

TEST_MODE = False     # False = боевой режим, True = тестовый (рандом)
MINUTES = 360         # сколько минут считаем (360 = 6 часов, 1440 = сутки, 10080 = неделя)

@app.route("/data")
def get_data():
    inflow = btc_inflow_last_minutes(
        minutes=MINUTES,
        test_mode=TEST_MODE
    )
    return jsonify({"btc_inflow": inflow})

@app.route("/")
def miniapp_index():
    return send_from_directory(MINIAPP_DIR, "index.html")

@app.route("/<path:path>")
def miniapp_files(path):
    return send_from_directory(MINIAPP_DIR, path)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)