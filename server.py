from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
import os
from config import PORT, DEBUG

from onchain import build_cluster

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(__file__)
MINIAPP_DIR = os.path.join(BASE_DIR, "miniapp")

@app.route("/data")
def data():
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
    app.run(host="0.0.0.0", port=PORT, debug=DEBUG)