from flask import Flask, jsonify, send_file
from onchain import build_cluster
import os

app = Flask(__name__)

@app.route("/")
def home():
    return send_file("index.html")

@app.route("/cluster")
def cluster():
    return jsonify(build_cluster())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))