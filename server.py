from flask import Flask, jsonify, send_from_directory
from onchain import build_cluster

app = Flask(__name__, static_folder=".")

@app.route("/")
def home():
    return send_from_directory(".", "index.html")

@app.route("/cluster")
def cluster():
    data = build_cluster()
    return jsonify(data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)