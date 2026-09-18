from flask import Flask, request, jsonify
from pathlib import Path
import json, time

app = Flask(__name__)

DATA = Path("/data")
DATA.mkdir(exist_ok=True)

CONFIG = DATA / "config.json"

def load_config():
    if CONFIG.exists():
        return json.loads(CONFIG.read_text())
    return {}

@app.route("/")
def index():
    cfg = load_config()
    return """
    <h1>Alexa Bring Sync 0.2.0</h1>
    <p>Port: 8154</p>
    <p>Konfiguration: %s</p>
    <form method="post" action="/setup">
    Amazon Benutzer:<br><input name="user"><br>
    Passwort:<br><input name="password" type="password"><br>
    <button>Speichern</button>
    </form>
    """ % ("vorhanden" if cfg else "fehlt")

@app.post("/setup")
def setup():
    CONFIG.write_text(json.dumps({
        "username": request.form.get("user", ""),
        "password_configured": True,
        "created": int(time.time())
    }, indent=2))
    return "Konfiguration gespeichert"

@app.get("/api/status")
def status():
    return jsonify({
        "version": "0.2.0",
        "port": 8154,
        "sync_interval_seconds": 5,
        "configured": CONFIG.exists()
    })

app.run(host="0.0.0.0", port=8154)
