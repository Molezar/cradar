from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
import os

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MINIAPP_DIR = os.path.join(BASE_DIR, "miniapp")

@app.route("/health")
def health():
    return "ok"

@app.route("/data")
def data():
    # импорт ТОЛЬКО при запросе
    from onchain import build_cluster

    cluster = build_cluster()
    return jsonify({
        "cold_wallet": "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo",
        "cluster_size": len(cluster),
        "addresses": cluster[:50]
    })

@app.route("/")
def index():
    return send_from_directory(MINIAPP_DIR, "index.html")

@app.route("/<path:path>")
def files(path):
    return send_from_directory(MINIAPP_DIR, path)

if __name__ == "__main__":
    # Берём PORT из окружения, если его нет — локально 8000
    port = int(os.environ.get("PORT", 8000))

    # DEBUG = True локально (если ENV=dev), иначе False
    ENV = os.environ.get("ENV", "dev")
    DEBUG = ENV == "dev"

    print("ENV:", ENV)
    print("PORT:", port)
    print("DEBUG:", DEBUG)

    app.run(
        host="0.0.0.0",
        port=port,
        debug=DEBUG
    )