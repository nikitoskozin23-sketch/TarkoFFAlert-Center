from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from providers.base import BaseProvider

try:
    from models import AlertEvent
except ImportError:
    from schemas import AlertEvent  # type: ignore


logger = logging.getLogger(__name__)

YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]


def _backend_root() -> Path:
    # В dev:
    #   .../backend/providers/youtube.py -> parents[1] == .../backend
    # В PyInstaller onedir:
    #   .../backend/_internal/providers/youtube.py -> parents[1] == .../backend/_internal
    # Это как раз то место, где лежат bundled data files.
    return Path(__file__).resolve().parents[1]


def _project_root() -> Path:
    return _backend_root().parent


def _resolve_path(path_value: str, prefer_credentials: bool = False) -> Path:
    raw = Path(str(path_value).strip())

    if raw.is_absolute():
        return raw

    candidates: list[Path] = []

    # 1) Относительно корня проекта / папки рядом с _internal
    candidates.append(_project_root() / raw)

    # 2) Относительно backend root (_internal в release, backend в dev)
    candidates.append(_backend_root() / raw)

    # 3) Если в config указан путь вида backend/credentials/...
    if raw.parts and raw.parts[0].lower() == "backend":
        stripped = Path(*raw.parts[1:]) if len(raw.parts) > 1 else Path()
        if str(stripped):
            candidates.append(_backend_root() / stripped)
            candidates.append(_project_root() / stripped)

    # 4) Если указан просто файл, пробуем типичные папки credentials
    if prefer_credentials and len(raw.parts) == 1:
        candidates.append(_backend_root() / "credentials" / raw.name)
        candidates.append(_project_root() / "credentials" / raw.name)
        candidates.append(_project_root() / "backend" / "credentials" / raw.name)

    seen: set[Path] = set()
    ordered_candidates: list[Path] = []
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate not in seen:
            seen.add(candidate)
            ordered_candidates.append(candidate)

    for candidate in ordered_candidates:
        if candidate.exists():
            return candidate

    return ordered_candidates[0] if ordered_candidates else raw.resolve()


class YouTubeProvider(BaseProvider):
    def __init__(self, config: dict[str, Any] | None, ctx):
        config = config or {}
        super().__init__(config, ctx)

        self.name = "youtube"
        self.ctx = ctx
        self.config = config

        self.token_file = str(config.get("token_file", "token.json"))
        self.broadcast_check_interval_sec = int(config.get("broadcast_check_interval_sec", 20))
        self.poll_interval_sec = int(config.get("poll_interval_sec", 5))
        self.error_retry_sec = int(config.get("error_retry_sec", 15))
        self.max_results = int(config.get("max_results", 200))

        self.default_duration_ms = int(
            config.get("default_duration_ms", config.get("duration_ms", 7000))
        )
        self.skip_existing_on_startup = bool(
            config.get(
                "skip_existing_on_startup",
                config.get("skip_existing_messages_on_start", True),
            )
        )
        self.emit_chat_messages = bool(config.get("emit_chat_messages", True))
        self.ignore_streamer_messages = bool(config.get("ignore_streamer_messages", False))

        self.youtube = None
        self.creds: Credentials | None = None

        self.active_broadcast_id: str | None = None
        self.active_broadcast_title: str | None = None
        self.active_live_chat_id: str | None = None

        self.next_page_token: str | None = None
        self.seen_message_ids: set[str] = set()
        self.startup_seed_done = False
        self.last_broadcast_check_ts = 0.0

    async def run(self) -> None:
        logger.info("YouTube provider: run() started")

        while True:
            try:
                await self._ensure_client()

                now = time.monotonic()
                need_broadcast_check = (
                    self.active_broadcast_id is None
                    or (now - self.last_broadcast_check_ts) >= self.broadcast_check_interval_sec
                )

                if need_broadcast_check:
                    self.last_broadcast_check_ts = now
                    await self._refresh_active_broadcast()

                if not self.active_broadcast_id or not self.active_live_chat_id:
                    await asyncio.sleep(self.broadcast_check_interval_sec)
                    continue

                sleep_sec = await self._poll_live_chat()
                await asyncio.sleep(max(1, int(sleep_sec)))

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("YouTube provider error")
                await asyncio.sleep(self.error_retry_sec)

    async def _ensure_client(self) -> None:
        token_path = _resolve_path(self.token_file, prefer_credentials=True)

        if not token_path.exists():
            raise FileNotFoundError(f"YouTube token file not found: {token_path}")

        if self.creds is None:
            self.creds = await asyncio.to_thread(
                Credentials.from_authorized_user_file,
                str(token_path),
                YOUTUBE_SCOPES,
            )

        if self.creds.expired and self.creds.refresh_token:
            await asyncio.to_thread(self.creds.refresh, Request())
            await self._save_credentials(token_path, self.creds)

        if not self.creds.valid:
            raise RuntimeError("YouTube credentials are invalid")

        if self.youtube is None:
            self.youtube = await asyncio.to_thread(
                build,
                "youtube",
                "v3",
                credentials=self.creds,
                cache_discovery=False,
            )

    async def _save_credentials(self, token_path: Path, creds: Credentials) -> None:
        data = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
        }
        await asyncio.to_thread(token_path.write_text, json.dumps(data, ensure_ascii=False), "utf-8")

    async def _refresh_active_broadcast(self) -> None:
        broadcast = await self._find_active_broadcast()

        if not broadcast:
            if self.active_broadcast_id is not None:
                logger.info("YouTube: активный эфир завершён или не найден")
            self._reset_active_broadcast()
            return

        broadcast_id = broadcast["id"]
        title = broadcast["title"]
        live_chat_id = broadcast["live_chat_id"]

        changed = (
            broadcast_id != self.active_broadcast_id
            or live_chat_id != self.active_live_chat_id
        )

        if changed:
            self.active_broadcast_id = broadcast_id
            self.active_broadcast_title = title
            self.active_live_chat_id = live_chat_id
            self.next_page_token = None
            self.seen_message_ids.clear()
            self.startup_seed_done = False

            logger.info(
                "YouTube: активный эфир найден | broadcast_id=%s | title=%s | liveChatId=%s",
                broadcast_id,
                title,
                live_chat_id,
            )

    async def _find_active_broadcast(self) -> dict[str, str] | None:
        request = self.youtube.liveBroadcasts().list(
            part="id,snippet,status",
            mine=True,
            maxResults=50,
        )
        response = await asyncio.to_thread(request.execute)

        for item in response.get("items", []):
            status = item.get("status", {}) or {}
            snippet = item.get("snippet", {}) or {}

            life_cycle = str(status.get("lifeCycleStatus", "")).lower()
            live_chat_id = snippet.get("liveChatId")

            if life_cycle in {"live", "livestarting"} and live_chat_id:
                return {
                    "id": item.get("id", ""),
                    "title": snippet.get("title", "YouTube Live"),
                    "live_chat_id": live_chat_id,
                }

        return None

    def _reset_active_broadcast(self) -> None:
        self.active_broadcast_id = None
        self.active_broadcast_title = None
        self.active_live_chat_id = None
        self.next_page_token = None
        self.seen_message_ids.clear()
        self.startup_seed_done = False

    async def _poll_live_chat(self) -> int:
        kwargs: dict[str, Any] = {
            "part": "id,snippet,authorDetails",
            "liveChatId": self.active_live_chat_id,
            "maxResults": self.max_results,
        }
        if self.next_page_token:
            kwargs["pageToken"] = self.next_page_token

        request = self.youtube.liveChatMessages().list(**kwargs)

        try:
            response = await asyncio.to_thread(request.execute)
        except HttpError as exc:
            status_code = getattr(exc.resp, "status", None)

            if status_code in (403, 404):
                logger.warning("YouTube: чат недоступен или эфир завершён, сбрасываю активный эфир")
                self._reset_active_broadcast()
                return self.broadcast_check_interval_sec

            raise

        items = response.get("items", []) or []
        self.next_page_token = response.get("nextPageToken")

        polling_interval_ms = int(response.get("pollingIntervalMillis", self.poll_interval_sec * 1000))
        sleep_sec = max(self.poll_interval_sec, polling_interval_ms // 1000)

        if self.skip_existing_on_startup and not self.startup_seed_done:
            skipped = 0
            for item in items:
                message_id = item.get("id")
                if message_id:
                    self.seen_message_ids.add(message_id)
                    skipped += 1

            self.startup_seed_done = True
            if skipped:
                logger.info("YouTube: пропущено %s существующих сообщений чата при старте", skipped)
            return sleep_sec

        for item in items:
            message_id = item.get("id")
            if not message_id or message_id in self.seen_message_ids:
                continue

            self.seen_message_ids.add(message_id)
            await self._handle_chat_item(item)

        return sleep_sec

    async def _handle_chat_item(self, item: dict[str, Any]) -> None:
        snippet = item.get("snippet", {}) or {}
        author = item.get("authorDetails", {}) or {}

        message_type = snippet.get("type", "")
        display_name = author.get("displayName", "YouTube user")
        is_owner = bool(author.get("isChatOwner"))

        if self.ignore_streamer_messages and is_owner:
            return

        if message_type == "textMessageEvent":
            if not self.emit_chat_messages:
                return

            message = snippet.get("displayMessage", "") or ""
            if not message.strip():
                return

            alert = self._build_alert(
                alert_type="custom",
                title="YouTube чат",
                message=message,
                user_name=display_name,
                raw=item,
            )
            await self.ctx.emit_alert(alert)
            return

        if message_type == "superChatEvent":
            details = snippet.get("superChatDetails", {}) or {}
            amount = details.get("amountDisplayString", "")
            message = snippet.get("displayMessage", "") or f"Поддержал канал на {amount}"

            alert = self._build_alert(
                alert_type="superchat",
                title="YouTube Super Chat",
                message=message,
                user_name=display_name,
                raw=item,
            )
            await self.ctx.emit_alert(alert)
            return

        if message_type == "superStickerEvent":
            details = snippet.get("superStickerDetails", {}) or {}
            amount = details.get("amountDisplayString", "")
            sticker = (details.get("superStickerMetadata", {}) or {}).get("altText", "Стикер")
            message = f"{sticker} {amount}".strip()

            alert = self._build_alert(
                alert_type="sticker",
                title="YouTube стикер",
                message=message,
                user_name=display_name,
                raw=item,
            )
            await self.ctx.emit_alert(alert)
            return

        if message_type in {"newSponsorEvent", "memberMilestoneChatEvent"}:
            message = snippet.get("displayMessage", "") or "Новый участник канала"

            alert = self._build_alert(
                alert_type="member",
                title="YouTube участник",
                message=message,
                user_name=display_name,
                raw=item,
            )
            await self.ctx.emit_alert(alert)
            return

    def _build_alert(
        self,
        alert_type: str,
        title: str,
        message: str,
        user_name: str,
        raw: dict[str, Any],
    ) -> AlertEvent:
        return AlertEvent(
            type=alert_type,
            platform="youtube",
            title=title,
            message=message,
            user_name=user_name,
            duration_ms=self.default_duration_ms,
            raw=raw,
        )