from flask import Flask, jsonify, send_from_directory, request
from onchain import get_coinglass_data
import os
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

MINIAPP_DIR = os.path.join(os.path.dirname(__file__), "miniapp")

# -----------------------
# Настройки
# -----------------------
DEFAULT_INTERVAL = "1h"  # 1h, 4h, 1d
DEFAULT_SYMBOL = "BTC"
DEFAULT_EXCHANGE = "Binance"

@app.route("/data")
def get_data():
    interval = request.args.get("interval", DEFAULT_INTERVAL)
    symbol = request.args.get("symbol", DEFAULT_SYMBOL)
    exchange = request.args.get("exchange", DEFAULT_EXCHANGE)

    try:
        data = get_coinglass_data(symbol=symbol, exchange=exchange, interval=interval)
    except Exception as e:
        return jsonify({"error": f"API error: {str(e)}"}), 500

    return jsonify(data)

@app.route("/")
def miniapp_index():
    return send_from_directory(MINIAPP_DIR, "index.html")

@app.route("/<path:path>")
def miniapp_files(path):
    return send_from_directory(MINIAPP_DIR, path)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)