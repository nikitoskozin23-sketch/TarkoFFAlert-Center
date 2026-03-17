from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.serving import make_server

from backend.queue_manager import QueueManager

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
CONFIG_DIR = ROOT / "config"
SETTINGS_PATH = CONFIG_DIR / "settings.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    "ad_enabled": True,
    "ad_text": "Скоро запуск сайта",
    "ad_subtext": "TarkoFFchanin.pro",
    "ad_follow": "Следи за анонсами",
    "music_volume": "0.35",
    "tts_volume": "1.00",
    "tts_voice": "default",
    "show_seconds": 4,
    "music_seconds": 2,
    "tts_seconds": 4,
}


def load_settings() -> dict[str, Any]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not SETTINGS_PATH.exists():
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        merged = DEFAULT_SETTINGS.copy()
        merged.update(data)
        return merged
    except Exception:
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()


def save_settings(data: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")
settings = load_settings()
logs: list[str] = []
queue = QueueManager(settings, logs)
_shutdown_server = None


@app.get("/")
def index():
    return jsonify({
        "name": "TarkoFF Stream Center Backend",
        "overlay": "http://127.0.0.1:8765/overlay",
        "control": "http://127.0.0.1:8765/control",
    })


@app.get("/overlay")
def overlay():
    return send_from_directory(WEB_DIR, "overlay.html")


@app.get("/control")
def control():
    return send_from_directory(WEB_DIR, "control.html")


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "pid": os.getpid()})


@app.get("/api/state")
def state():
    return jsonify(queue.state())


@app.get("/api/settings")
def get_settings():
    return jsonify({"settings": settings})


@app.post("/api/settings")
def update_settings():
    data = request.get_json(silent=True) or {}
    for key in [
        "ad_text",
        "ad_subtext",
        "ad_follow",
        "music_volume",
        "tts_volume",
        "tts_voice",
        "show_seconds",
        "music_seconds",
        "tts_seconds",
    ]:
        if key in data and data[key] != "":
            settings[key] = data[key]
    save_settings(settings)
    queue.add_log("Настройки обновлены из GUI/control")
    return jsonify({"ok": True, "settings": settings})


@app.post("/api/toggle-ad")
def toggle_ad():
    data = request.get_json(silent=True) or {}
    settings["ad_enabled"] = bool(data.get("enabled", False))
    save_settings(settings)
    queue.add_log(f"Реклама сайта {'включена' if settings['ad_enabled'] else 'выключена'}")
    return jsonify({"ok": True, "ad_enabled": settings["ad_enabled"]})


@app.post("/api/test-alert")
def test_alert():
    data = request.get_json(silent=True) or {}
    donor = str(data.get("donor", "TarkoFF Supporter"))
    amount = str(data.get("amount", "100"))
    message = str(data.get("message", "Тестовый донат"))
    queue.add_alert(donor, amount, message)
    return jsonify({"ok": True})


@app.get("/api/logs")
def get_logs():
    return jsonify({"logs": logs[-300:]})


@app.post("/api/shutdown")
def shutdown():
    def _shutdown() -> None:
        if _shutdown_server:
            _shutdown_server.shutdown()

    threading.Thread(target=_shutdown, daemon=True).start()
    return jsonify({"ok": True, "message": "shutdown scheduled"})


class ServerThread(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.server = make_server("127.0.0.1", 8765, app)
        self.ctx = app.app_context()
        self.ctx.push()

    def run(self) -> None:
        global _shutdown_server
        _shutdown_server = self.server
        queue.add_log("Backend запущен на http://127.0.0.1:8765")
        self.server.serve_forever()


if __name__ == "__main__":
    server = ServerThread()
    server.start()
    server.join()
