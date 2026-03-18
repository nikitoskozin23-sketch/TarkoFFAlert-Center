from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import math
import os
import re
import time
import urllib.parse
import uuid
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import edge_tts
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import load_config
from models import AlertEvent
from obs_controller import OBSController
from providers import (
    DonationAlertsProvider,
    FakeProvider,
    TrovoProvider,
    TwitchProvider,
    VKPlayProvider,
    YouTubeProvider,
)
from providers.base import ProviderContext


BASE_DIR = Path(__file__).resolve().parent
CONFIG = (
    load_config(BASE_DIR / "config.yaml")
    if (BASE_DIR / "config.yaml").exists()
    else load_config(BASE_DIR / "config.example.yaml")
)

logging.basicConfig(
    level=logging.DEBUG if CONFIG["app"].get("debug") else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,
)
logging.getLogger("googleapiclient.discovery").setLevel(logging.WARNING)
logging.getLogger("websockets.client").setLevel(logging.WARNING)
logging.getLogger("providers.vk_play").setLevel(logging.INFO)
log = logging.getLogger("custom_alerts")

TTS_DIR = BASE_DIR / "static" / "tts"
TTS_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE", "ru-RU-DmitryNeural")
EDGE_TTS_RATE = os.getenv("EDGE_TTS_RATE", "-5%")
EDGE_TTS_VOLUME = os.getenv("EDGE_TTS_VOLUME", "+12%")
EDGE_TTS_PITCH = os.getenv("EDGE_TTS_PITCH", "-4Hz")

PROJECT_ROOT = BASE_DIR.parent
GUI_SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.json"

DEFAULT_GUI_SETTINGS: dict[str, Any] = {
    "show_site_ads": False,
    "ad_title": "Скоро запуск сайта!",
    "ad_line2": "TarkoFFchanin.pro",
    "ad_line3": "Следи за анонсами",
    "music_volume": "0.35",
    "tts_volume": "1.00",
    "tts_voice": "default",
}

RUNTIME_SETTINGS: dict[str, Any] = {}
_OBS_TEMP_HIDE_TASKS: dict[str, asyncio.Task] = {}

_AMOUNT_RE = re.compile(
    r"^\s*([+-]?\d[\d\s\u00A0]*(?:[.,]\d+)?(?:[eE][+-]?\d+)?)(?:\s*([A-Za-zА-Яа-я₽$€]+))?\s*$",
    re.UNICODE,
)


def load_gui_settings() -> dict[str, Any]:
    GUI_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not GUI_SETTINGS_PATH.exists():
        save_gui_settings(DEFAULT_GUI_SETTINGS)
        return DEFAULT_GUI_SETTINGS.copy()

    try:
        raw = GUI_SETTINGS_PATH.read_text(encoding="utf-8").strip()
        if not raw:
            save_gui_settings(DEFAULT_GUI_SETTINGS)
            return DEFAULT_GUI_SETTINGS.copy()

        data = json.loads(raw)
        if not isinstance(data, dict):
            save_gui_settings(DEFAULT_GUI_SETTINGS)
            return DEFAULT_GUI_SETTINGS.copy()

        merged = DEFAULT_GUI_SETTINGS.copy()
        merged.update(data)
        return merged
    except Exception:
        save_gui_settings(DEFAULT_GUI_SETTINGS)
        return DEFAULT_GUI_SETTINGS.copy()


def save_gui_settings(data: dict[str, Any]) -> None:
    merged = DEFAULT_GUI_SETTINGS.copy()
    merged.update(data)

    GUI_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    GUI_SETTINGS_PATH.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def refresh_runtime_settings() -> None:
    global RUNTIME_SETTINGS
    RUNTIME_SETTINGS = load_gui_settings()


def get_runtime_tts_voice() -> str:
    refresh_runtime_settings()

    raw_voice = str(RUNTIME_SETTINGS.get("tts_voice") or "").strip()
    if not raw_voice or raw_voice.lower() == "default":
        return DEFAULT_EDGE_TTS_VOICE
    return raw_voice


refresh_runtime_settings()


class AlertBus:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.history: list[AlertEvent] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.clients.add(websocket)
        log.info("Overlay client connected. Total: %s", len(self.clients))

    def disconnect(self, websocket: WebSocket) -> None:
        self.clients.discard(websocket)
        log.info("Overlay client disconnected. Total: %s", len(self.clients))

    async def emit(self, event: AlertEvent) -> None:
        async with self._lock:
            self.history.append(event)
            self.history = self.history[-100:]

        payload = event.model_dump()

        display_amount = format_amount_display(getattr(event, "amount", None))
        if display_amount:
            payload["amount"] = display_amount

        try:
            tts_text = build_tts_text_from_event(event)
            if tts_text:
                payload["tts_text"] = tts_text
                payload["tts_url"] = await generate_tts_file(tts_text)
            else:
                payload["tts_text"] = None
                payload["tts_url"] = None
        except Exception as exc:
            payload["tts_text"] = None
            payload["tts_url"] = None
            log.exception("TTS generation failed: %s", exc)

        dead_clients: list[WebSocket] = []
        for client in self.clients:
            try:
                await client.send_text(json.dumps(payload, ensure_ascii=False))
            except Exception:
                dead_clients.append(client)

        for client in dead_clients:
            self.disconnect(client)

        log.info("Alert emitted: %s | %s | %s", event.platform, event.type, event.title)


bus = AlertBus()
ctx = ProviderContext(emit_alert=bus.emit)
fake_provider = FakeProvider({"enabled": True}, ctx)
obs_controller = OBSController()

providers_cfg = CONFIG.get("providers", {}) or {}

providers = [
    TwitchProvider(providers_cfg.get("twitch") or {}, ctx),
    YouTubeProvider(providers_cfg.get("youtube") or {}, ctx),
    TrovoProvider(providers_cfg.get("trovo") or {}, ctx),
    DonationAlertsProvider(providers_cfg.get("donation_alerts") or {}, ctx),
    VKPlayProvider(providers_cfg.get("vk_play") or {}, ctx),
]

VK_CONFIG = providers_cfg.get("vk_play") or {}
VK_SEEN_IDS: deque[str] = deque(maxlen=1000)
VK_SEEN_SET: set[str] = set()


def cleanup_old_tts_files(max_age_seconds: int = 3600) -> None:
    now = time.time()
    for file_path in TTS_DIR.glob("*.mp3"):
        try:
            if now - file_path.stat().st_mtime > max_age_seconds:
                file_path.unlink(missing_ok=True)
        except OSError:
            pass


def normalize_currency_label(currency: Any) -> str:
    cur = str(currency or "").strip().upper()
    if not cur:
        return ""
    if cur in {"RUB", "RUR", "₽"}:
        return "RUB"
    if cur in {"USD", "$"}:
        return "USD"
    if cur in {"EUR", "€"}:
        return "EUR"
    return cur


def parse_amount_value(raw_amount: Any, raw_currency: Any = None) -> tuple[float | None, str]:
    fallback_currency = normalize_currency_label(raw_currency)

    if raw_amount in (None, ""):
        return None, fallback_currency

    text = str(raw_amount).strip()
    if not text:
        return None, fallback_currency

    text = text.replace("\u00A0", " ").replace(",", ".")

    match = _AMOUNT_RE.match(text)
    if not match:
        return None, fallback_currency

    number_text = match.group(1).replace(" ", "")
    inline_currency = normalize_currency_label(match.group(2) or "")
    currency = inline_currency or fallback_currency

    try:
        value = float(number_text)
    except ValueError:
        return None, currency

    if math.isnan(value) or math.isinf(value):
        return None, currency

    return value, currency


def format_number_ru(value: float) -> str:
    if float(value).is_integer():
        return f"{int(value):,}".replace(",", " ")
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def format_amount_display(raw_amount: Any, raw_currency: Any = None) -> str | None:
    value, currency = parse_amount_value(raw_amount, raw_currency)
    if value is None:
        text = str(raw_amount or "").strip()
        return text or None

    formatted = format_number_ru(value)

    if currency == "RUB":
        return f"{formatted} ₽"
    if currency:
        return f"{formatted} {currency}"
    return formatted


def format_amount_for_tts(raw_amount: Any, raw_currency: Any = None) -> str:
    value, currency = parse_amount_value(raw_amount, raw_currency)
    if value is None:
        text = str(raw_amount or "").strip()
        if not text:
            return ""
        text = text.replace("₽", " рублей ")
        text = text.replace("RUB", " рублей ")
        text = text.replace("RUR", " рублей ")
        text = text.replace("USD", " долларов ")
        text = text.replace("EUR", " евро ")
        text = text.replace("$", " долларов ")
        text = text.replace("€", " евро ")
        return re.sub(r"\s+", " ", text).strip()

    formatted = format_number_ru(value)

    if currency == "RUB":
        return f"{formatted} рублей"
    if currency == "USD":
        return f"{formatted} долларов"
    if currency == "EUR":
        return f"{formatted} евро"
    if currency:
        return f"{formatted} {currency}"
    return formatted


def clean_tts_text(value: Any, max_len: int = 240) -> str:
    text = str(value or "").strip()
    text = re.sub(r"https?://\S+", "ссылка", text, flags=re.IGNORECASE)
    text = text.replace("₽", " рублей ")
    text = text.replace("$", " долларов ")
    text = text.replace("€", " евро ")
    text = text.replace("&", " и ")
    text = re.sub(r"[<>\\/*_~`#^|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def build_tts_text_from_event(event: AlertEvent) -> str | None:
    event_type = str(getattr(event, "type", "") or "").lower()
    if event_type not in {"donation", "donat", "tip", "superchat"}:
        return None

    username = clean_tts_text(getattr(event, "username", None), 40) or "Аноним"
    amount = format_amount_for_tts(getattr(event, "amount", None))
    message = clean_tts_text(getattr(event, "message", None), 240)

    parts = [f"Донат от {username}."]
    if amount:
        parts.append(f"Сумма {amount}.")
    if message:
        parts.append(f"Сообщение: {message}")
    return " ".join(parts).strip()


async def generate_tts_file(text: str) -> str:
    cleanup_old_tts_files()

    file_name = f"{uuid.uuid4().hex}.mp3"
    file_path = TTS_DIR / file_name

    communicate = edge_tts.Communicate(
        text=text,
        voice=get_runtime_tts_voice(),
        rate=EDGE_TTS_RATE,
        volume=EDGE_TTS_VOLUME,
        pitch=EDGE_TTS_PITCH,
    )
    await communicate.save(str(file_path))
    return f"/static/tts/{file_name}"


def remember_vk_event_id(event_id: str) -> None:
    if not event_id or event_id in VK_SEEN_SET:
        return
    if len(VK_SEEN_IDS) == VK_SEEN_IDS.maxlen:
        expired = VK_SEEN_IDS.popleft()
        VK_SEEN_SET.discard(expired)
    VK_SEEN_IDS.append(event_id)
    VK_SEEN_SET.add(event_id)


def first_non_empty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def stringify_amount(data: dict[str, Any]) -> str | None:
    amount = (
        data.get("amount")
        or data.get("sum")
        or data.get("price")
        or data.get("value")
        or data.get("donation_amount")
    )
    currency = (
        data.get("currency")
        or data.get("currency_code")
        or data.get("amount_currency")
        or data.get("donation_currency")
    )
    if amount in (None, ""):
        return None
    amount_text = str(amount).strip()
    currency_text = str(currency).strip() if currency not in (None, "") else ""
    return f"{amount_text} {currency_text}".strip()


def vk_event_to_alert(payload: dict[str, Any]) -> AlertEvent | None:
    event_type = str(payload.get("type") or "").strip()
    event_type_lower = event_type.lower()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}

    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    sender = data.get("sender") if isinstance(data.get("sender"), dict) else {}

    username = first_non_empty(
        data.get("nick"),
        data.get("nickname"),
        data.get("username"),
        data.get("display_name"),
        data.get("user_nick"),
        user.get("nick"),
        user.get("nickname"),
        sender.get("nick"),
        sender.get("nickname"),
        "VK зритель",
    )

    avatar_url = first_non_empty(
        data.get("avatar_url"),
        user.get("avatar_url"),
        sender.get("avatar_url"),
    ) or None

    message = first_non_empty(
        data.get("message"),
        data.get("text"),
        data.get("comment"),
        data.get("body"),
    )

    amount = stringify_amount(data)
    amount_display = format_amount_display(amount) if amount else None

    duration_ms = int(VK_CONFIG.get("duration_ms", CONFIG["app"].get("default_duration_ms", 7000)))

    if "follow" in event_type_lower:
        return AlertEvent(
            type="follow",
            platform="vk_play",
            title="Новый фоллоу",
            message=message or "Подписался на канал",
            username=username,
            avatar_url=avatar_url,
            duration_ms=duration_ms,
            raw=payload,
        )

    if "gift" in event_type_lower and "sub" in event_type_lower:
        return AlertEvent(
            type="gift_sub",
            platform="vk_play",
            title="Подарочная подписка",
            message=message or "Подарил подписку",
            username=username,
            avatar_url=avatar_url,
            duration_ms=duration_ms,
            raw=payload,
        )

    if "resub" in event_type_lower:
        return AlertEvent(
            type="resubscribe",
            platform="vk_play",
            title="Продление подписки",
            message=message or "Продлил подписку",
            username=username,
            avatar_url=avatar_url,
            duration_ms=duration_ms,
            raw=payload,
        )

    if "sub" in event_type_lower or "subscribe" in event_type_lower:
        return AlertEvent(
            type="subscribe",
            platform="vk_play",
            title="Новая подписка",
            message=message or "Оформил подписку",
            username=username,
            avatar_url=avatar_url,
            duration_ms=duration_ms,
            raw=payload,
        )

    if "donat" in event_type_lower or "donation" in event_type_lower:
        return AlertEvent(
            type="donation",
            platform="vk_play",
            title="Новый донат",
            message=message,
            username=username,
            amount=amount_display,
            avatar_url=avatar_url,
            duration_ms=duration_ms,
            raw=payload,
        )

    if bool(VK_CONFIG.get("emit_unknown_events", False)):
        short_message = message or f"Тип события: {event_type}"
        return AlertEvent(
            type="custom",
            platform="vk_play",
            title=f"VK Play: {event_type or 'unknown'}",
            message=short_message,
            username=username,
            amount=amount_display,
            avatar_url=avatar_url,
            duration_ms=duration_ms,
            raw=payload,
        )

    return None


def _obs_task_key(scene_name: str, source_name: str) -> str:
    return f"{scene_name}::{source_name}"


def cancel_hide_source(scene_name: str, source_name: str) -> None:
    key = _obs_task_key(scene_name, source_name)
    task = _OBS_TEMP_HIDE_TASKS.get(key)
    if task and not task.done():
        task.cancel()
    _OBS_TEMP_HIDE_TASKS.pop(key, None)


async def _hide_source_later(scene_name: str, source_name: str, delay_sec: int) -> None:
    key = _obs_task_key(scene_name, source_name)
    try:
        await asyncio.sleep(max(1, int(delay_sec)))
        ok, message = obs_controller.hide_source(scene_name, source_name)
        if ok:
            log.info("OBS auto-hide source done: %s / %s", scene_name, source_name)
        else:
            log.warning("OBS auto-hide source failed: %s", message)
    except asyncio.CancelledError:
        log.info("OBS auto-hide cancelled: %s / %s", scene_name, source_name)
        raise
    finally:
        current = _OBS_TEMP_HIDE_TASKS.get(key)
        if current is asyncio.current_task():
            _OBS_TEMP_HIDE_TASKS.pop(key, None)


def schedule_hide_source(scene_name: str, source_name: str, delay_sec: int) -> None:
    key = _obs_task_key(scene_name, source_name)

    current = _OBS_TEMP_HIDE_TASKS.get(key)
    if current and not current.done():
        current.cancel()

    task = asyncio.create_task(_hide_source_later(scene_name, source_name, delay_sec))
    _OBS_TEMP_HIDE_TASKS[key] = task


def _show_source_temp_impl(
    scene_name: str,
    source_name: str,
    duration_sec: int,
    success_text: str,
) -> dict[str, Any]:
    if not obs_controller.is_connected():
        return {
            "ok": False,
            "message": "OBS не подключён. Сначала вызови /api/obs/connect",
            "scene_name": scene_name,
            "source_name": source_name,
            "duration_sec": duration_sec,
        }

    ok, message = obs_controller.show_source(scene_name, source_name)
    if not ok:
        return {
            "ok": False,
            "message": message,
            "scene_name": scene_name,
            "source_name": source_name,
            "duration_sec": duration_sec,
        }

    schedule_hide_source(scene_name, source_name, duration_sec)

    return {
        "ok": True,
        "message": success_text,
        "scene_name": scene_name,
        "source_name": source_name,
        "duration_sec": duration_sec,
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    await fake_provider.start()
    for provider in providers:
        await provider.start()
    yield
    for task in list(_OBS_TEMP_HIDE_TASKS.values()):
        if not task.done():
            task.cancel()
    await fake_provider.stop()
    for provider in providers:
        await provider.stop()


app = FastAPI(title="Custom OBS Alerts", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def root() -> str:
    return "<h2>Custom OBS Alerts запущен</h2><p>Overlay: <a href='/overlay'>/overlay</a><br>Control: <a href='/control'>/control</a></p>"


@app.get("/overlay")
async def overlay() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "overlay.html")


@app.get("/control")
async def control() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "control.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    refresh_runtime_settings()
    return {
        "ok": True,
        "clients": len(bus.clients),
        "history": len(bus.history),
        "providers": [provider.name for provider in providers],
        "tts": {
            "voice": get_runtime_tts_voice(),
            "default_voice": DEFAULT_EDGE_TTS_VOICE,
            "rate": EDGE_TTS_RATE,
            "volume": EDGE_TTS_VOLUME,
            "pitch": EDGE_TTS_PITCH,
        },
        "settings": RUNTIME_SETTINGS,
    }


@app.get("/api/history")
async def history() -> list[dict[str, Any]]:
    return [event.model_dump() for event in bus.history[-25:]]


@app.get("/api/settings")
async def get_settings() -> dict[str, Any]:
    refresh_runtime_settings()
    return {"ok": True, "settings": RUNTIME_SETTINGS}


@app.post("/api/settings")
async def update_settings(payload: dict[str, Any]) -> dict[str, Any]:
    refresh_runtime_settings()

    allowed_keys = {
        "show_site_ads",
        "ad_title",
        "ad_line2",
        "ad_line3",
        "music_volume",
        "tts_volume",
        "tts_voice",
    }

    updated = RUNTIME_SETTINGS.copy()
    for key in allowed_keys:
        if key in payload:
            updated[key] = payload[key]

    save_gui_settings(updated)
    refresh_runtime_settings()

    return {"ok": True, "settings": RUNTIME_SETTINGS}


@app.post("/api/toggle-ad")
async def toggle_ad(payload: dict[str, Any]) -> dict[str, Any]:
    refresh_runtime_settings()

    enabled = bool(payload.get("enabled", False))
    updated = RUNTIME_SETTINGS.copy()
    updated["show_site_ads"] = enabled

    save_gui_settings(updated)
    refresh_runtime_settings()

    return {"ok": True, "show_site_ads": enabled, "settings": RUNTIME_SETTINGS}


@app.get("/api/obs/status")
async def obs_status() -> dict[str, Any]:
    if not obs_controller.is_connected():
        return {
            "ok": True,
            "connected": False,
            "version": {},
            "scenes": [],
            "current_scene": "",
        }

    try:
        version = obs_controller.get_version()
        scenes = obs_controller.get_scene_names()
        current_scene = obs_controller.get_current_program_scene()
        return {
            "ok": True,
            "connected": True,
            "version": version,
            "scenes": scenes,
            "current_scene": current_scene,
        }
    except Exception as e:
        return {
            "ok": False,
            "connected": False,
            "error": str(e),
            "version": {},
            "scenes": [],
            "current_scene": "",
        }


@app.get("/api/obs/scenes-and-sources")
async def obs_scenes_and_sources() -> dict[str, Any]:
    if not obs_controller.is_connected():
        return {
            "ok": False,
            "message": "OBS не подключён",
            "current_scene": "",
            "scenes": [],
            "sources_by_scene": {},
        }

    try:
        scenes = obs_controller.get_scene_names()
        current_scene = obs_controller.get_current_program_scene()

        sources_by_scene: dict[str, list[str]] = {}
        for scene_name in scenes:
            try:
                sources_by_scene[scene_name] = obs_controller.get_scene_items(scene_name)
            except Exception:
                sources_by_scene[scene_name] = []

        return {
            "ok": True,
            "current_scene": current_scene,
            "scenes": scenes,
            "sources_by_scene": sources_by_scene,
        }
    except Exception as e:
        return {
            "ok": False,
            "message": str(e),
            "current_scene": "",
            "scenes": [],
            "sources_by_scene": {},
        }


@app.post("/api/obs/connect")
async def obs_connect(payload: dict[str, Any]) -> dict[str, Any]:
    host = str(payload.get("host") or "127.0.0.1").strip()
    port = int(payload.get("port") or 4455)
    password = str(payload.get("password") or "")

    ok, message = obs_controller.connect(host=host, port=port, password=password)

    result: dict[str, Any] = {
        "ok": ok,
        "message": message,
        "connected": obs_controller.is_connected(),
    }

    if obs_controller.is_connected():
        try:
            result["version"] = obs_controller.get_version()
            result["scenes"] = obs_controller.get_scene_names()
            result["current_scene"] = obs_controller.get_current_program_scene()
        except Exception as e:
            result["version"] = {}
            result["scenes"] = []
            result["current_scene"] = ""
            result["warning"] = str(e)
    else:
        result["version"] = {}
        result["scenes"] = []
        result["current_scene"] = ""

    return result


@app.post("/api/obs/show-source")
async def obs_show_source(payload: dict[str, Any]) -> dict[str, Any]:
    scene_name = str(payload.get("scene_name") or "").strip()
    source_name = str(payload.get("source_name") or "").strip()

    ok, message = obs_controller.show_source(scene_name, source_name)
    return {
        "ok": ok,
        "message": message,
        "scene_name": scene_name,
        "source_name": source_name,
    }


@app.post("/api/obs/hide-source")
async def obs_hide_source(payload: dict[str, Any]) -> dict[str, Any]:
    scene_name = str(payload.get("scene_name") or "").strip()
    source_name = str(payload.get("source_name") or "").strip()

    cancel_hide_source(scene_name, source_name)
    ok, message = obs_controller.hide_source(scene_name, source_name)
    return {
        "ok": ok,
        "message": message,
        "scene_name": scene_name,
        "source_name": source_name,
    }


@app.post("/api/obs/show-source-temp")
async def obs_show_source_temp(payload: dict[str, Any]) -> dict[str, Any]:
    scene_name = str(payload.get("scene_name") or "").strip()
    source_name = str(payload.get("source_name") or "").strip()
    duration_sec = int(payload.get("duration_sec") or 8)

    return _show_source_temp_impl(
        scene_name=scene_name,
        source_name=source_name,
        duration_sec=duration_sec,
        success_text=f"Источник показан на {duration_sec} сек: {source_name}",
    )


@app.post("/api/test")
async def send_test_alert(payload: dict[str, Any]) -> dict[str, Any]:
    provider = str(payload.get("provider") or payload.get("platform") or "donation_alerts").strip()
    event_type = str(payload.get("event_type") or payload.get("type") or "donation").strip()
    title = str(payload.get("title") or "Новый донат").strip()
    username = str(
        payload.get("donor")
        or payload.get("username")
        or payload.get("sender")
        or "TarkoFF Supporter"
    ).strip()
    amount = str(payload.get("amount") or "250").strip()
    message = str(payload.get("message") or "Тест из GUI").strip()

    event = AlertEvent(
        type=event_type,
        platform=provider,
        title=title,
        username=username,
        amount=amount,
        message=message,
        raw=payload,
    )

    await bus.emit(event)
    return {"ok": True, "event": event.model_dump()}


@app.post("/api/demo-pack")
async def demo_pack() -> dict[str, Any]:
    await fake_provider.emit_demo_pack()
    return {"ok": True}


@app.post("/vk/webhook")
async def vk_webhook(request: Request) -> JSONResponse:
    secret_key = str(VK_CONFIG.get("secret_key") or "").strip()
    linked_user_id = str(VK_CONFIG.get("user_id") or "").strip()

    if not secret_key:
        return JSONResponse({"id": "0", "status": "unprocessable"})

    raw_body = await request.body()
    parsed = urllib.parse.parse_qs(raw_body.decode("utf-8"), keep_blank_values=True)

    event_raw = parsed.get("event", [None])[0]
    signature = parsed.get("signature", [None])[0]

    if not event_raw or not signature:
        return JSONResponse({"id": "0", "status": "unprocessable"})

    expected_signature = hashlib.sha256((event_raw + secret_key).encode("utf-8")).hexdigest()
    if not hmac.compare_digest(str(signature).lower(), expected_signature.lower()):
        event_id = "0"
        try:
            bad_payload = json.loads(event_raw)
            event_id = str(bad_payload.get("id") or "0")
        except Exception:
            pass
        return JSONResponse({"id": event_id, "status": "invalid_signature"})

    try:
        payload = json.loads(event_raw)
    except json.JSONDecodeError:
        return JSONResponse({"id": "0", "status": "unprocessable"})

    event_id = str(payload.get("id") or "0")
    event_user_id = str(payload.get("user_id") or "").strip()
    event_type = str(payload.get("type") or "").strip()

    if linked_user_id and event_user_id and linked_user_id != event_user_id:
        return JSONResponse({"id": event_id, "status": "not_linked"})

    if event_id in VK_SEEN_SET:
        return JSONResponse({"id": event_id, "status": "already_processed"})

    remember_vk_event_id(event_id)

    log.info("VK Play webhook received: type=%s id=%s", event_type, event_id)

    event = vk_event_to_alert(payload)
    if event:
        await bus.emit(event)

    return JSONResponse({"id": event_id, "status": "ok"})


@app.websocket("/ws/overlay")
async def overlay_ws(websocket: WebSocket) -> None:
    await bus.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        bus.disconnect(websocket)
    except Exception:
        bus.disconnect(websocket)


if __name__ == "__main__":
    import sys
    import uvicorn

    is_frozen = getattr(sys, "frozen", False)

    uvicorn.run(
        app if is_frozen else "main:app",
        host=CONFIG["server"]["host"],
        port=int(CONFIG["server"]["port"]),
        reload=False if is_frozen else True,
    )