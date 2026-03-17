from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx
import websockets

from models import AlertEvent
from providers.base import BaseProvider

log = logging.getLogger(__name__)


class VKPlayProvider(BaseProvider):
    name = "vk_play"

    API_BASE = "https://apidev.live.vkvideo.ru/v1"
    WS_URL = "wss://pubsub-dev.live.vkvideo.ru/connection/websocket?format=json&cf_protocol_version=v2"

    def __init__(self, config: dict[str, Any], ctx: Any):
        super().__init__(config, ctx)
        self._seen_chat_ids = set()
        self._seen_chat_ids_queue = []
        self._seen_chat_ids_limit = 500

    async def run(self) -> None:
        log.info("VK Play provider: run() started")

        access_token = str(self.config.get("access_token", "")).strip()
        if not access_token:
            log.warning("VK Play включён, но access_token пустой в config.yaml")
            while not self._stop.is_set():
                await asyncio.sleep(3600)
            return

        reconnect_delay = 3

        while not self._stop.is_set():
            try:
                await self._run_once(access_token)
                reconnect_delay = 3
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("VK Play provider error: %s", exc)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30)

    async def _run_once(self, access_token: str) -> None:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(headers=headers, timeout=20.0) as client:
            ws_token = await self._fetch_ws_token(client)
            log.info("VK Play: websocket token received")

            channels = self._collect_channels()
            log.info("VK Play: collected channels: %s", [item["channel"] for item in channels])

            if not channels:
                raise RuntimeError("VK Play: не найдено ни одного канала в config.yaml")

            limited_channels = [ch for ch in channels if ch["name"].startswith("limited")]
            limited_channel_names = [item["channel"] for item in limited_channels]

            limited_tokens: dict[str, str] = {}
            if limited_channel_names:
                limited_tokens = await self._fetch_subscription_tokens(client, limited_channel_names)
                log.info(
                    "VK Play: limited subscription tokens received: %s",
                    list(limited_tokens.keys()),
                )

            request_channels: dict[int, str] = {}

            async with websockets.connect(
                self.WS_URL,
                ping_interval=None,
                ping_timeout=None,
                close_timeout=10,
                max_size=2**22,
            ) as ws:
                await self._send_connect(ws, ws_token)
                log.info("VK Play: websocket connected")

                request_id = 2
                for item in channels:
                    channel_name = item["channel"]
                    token = limited_tokens.get(channel_name)
                    await self._send_subscribe(ws, request_id, channel_name, token=token)
                    request_channels[request_id] = channel_name
                    log.info("VK Play: subscribe -> %s", channel_name)
                    request_id += 1

                while not self._stop.is_set():
                    raw_message = await ws.recv()
                    for payload in self._decode_ws_payload(raw_message):
                        if payload == {}:
                            await ws.send("{}")
                            log.debug("VK Play: protocol pong sent")
                            continue

                        await self._handle_ws_payload(payload, request_channels)

    async def _fetch_ws_token(self, client: httpx.AsyncClient) -> str:
        response = await client.get(f"{self.API_BASE}/websocket/token")
        response.raise_for_status()
        token = (response.json().get("data") or {}).get("token")
        if not token:
            raise RuntimeError("VK Play: /websocket/token не вернул token")
        return str(token)

    async def _fetch_subscription_tokens(
        self,
        client: httpx.AsyncClient,
        channels: list[str],
    ) -> dict[str, str]:
        if not channels:
            return {}

        response = await client.get(
            f"{self.API_BASE}/websocket/subscription_token",
            params={"channels": ",".join(channels)},
        )
        response.raise_for_status()

        result: dict[str, str] = {}
        tokens = (response.json().get("data") or {}).get("channel_tokens") or []
        for item in tokens:
            channel = item.get("channel")
            token = item.get("token")
            if channel and token:
                result[str(channel)] = str(token)

        return result

    def _collect_channels(self) -> list[dict[str, str]]:
        channels_cfg = self.config.get("ws_channels") or {}
        if not isinstance(channels_cfg, dict):
            return []

        selected_names = self.config.get("subscribe_channels") or [
            "info",
            "chat",
            "channel_points",
        ]

        result: list[dict[str, str]] = []
        for name in selected_names:
            value = channels_cfg.get(name)
            if value:
                result.append({"name": str(name), "channel": str(value)})

        return result

    async def _send_connect(self, ws, token: str) -> None:
        payload = {
            "id": 1,
            "connect": {
                "token": token,
            },
        }
        await ws.send(json.dumps(payload, ensure_ascii=False))

    async def _send_subscribe(
        self,
        ws,
        request_id: int,
        channel: str,
        token: str | None = None,
    ) -> None:
        subscribe_data: dict[str, Any] = {"channel": channel}
        if token:
            subscribe_data["token"] = token

        payload = {
            "id": request_id,
            "subscribe": subscribe_data,
        }
        await ws.send(json.dumps(payload, ensure_ascii=False))

    def _decode_ws_payload(self, raw_message: Any) -> list[dict[str, Any]]:
        if isinstance(raw_message, bytes):
            raw_message = raw_message.decode("utf-8", errors="ignore")

        parts = [part.strip() for part in str(raw_message).splitlines() if part.strip()]
        payloads: list[dict[str, Any]] = []

        for part in parts:
            try:
                data = json.loads(part)
            except json.JSONDecodeError:
                log.debug("VK Play: не удалось распарсить websocket payload: %r", part)
                continue

            if isinstance(data, list):
                payloads.extend(item for item in data if isinstance(item, dict))
            elif isinstance(data, dict):
                payloads.append(data)

        return payloads

    async def _handle_ws_payload(
        self,
        payload: dict[str, Any],
        request_channels: dict[int, str],
    ) -> None:
        if payload.get("id") == 1 and "connect" in payload:
            log.info("VK Play: connect confirmed")
            return

        if "subscribe" in payload and payload.get("id"):
            req_id = int(payload["id"])
            channel = request_channels.get(req_id)
            log.info("VK Play: subscribe confirmed -> %s", channel)
            return

        if "error" in payload and payload.get("id"):
            req_id = int(payload["id"])
            channel = request_channels.get(req_id)
            log.warning("VK Play: subscribe error -> %s | %s", channel, payload.get("error"))
            return

        push = payload.get("push")
        if isinstance(push, dict):
            channel = str(push.get("channel") or "")
            pub = push.get("pub") or {}
            event_data = pub.get("data") if isinstance(pub, dict) else None
            if isinstance(event_data, dict):
                await self._handle_vk_event(channel, event_data)
                return

        publication = payload.get("publication")
        if isinstance(publication, dict):
            channel = str(publication.get("channel") or "")
            event_data = publication.get("data")
            if isinstance(event_data, dict):
                await self._handle_vk_event(channel, event_data)
                return

        pub = payload.get("pub")
        if isinstance(pub, dict):
            channel = str(payload.get("channel") or "")
            event_data = pub.get("data")
            if isinstance(event_data, dict):
                await self._handle_vk_event(channel, event_data)
                return

        log.debug("VK Play raw payload: %s", payload)

    async def _handle_vk_event(self, channel: str, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "").strip()
        data = event.get("data") if isinstance(event.get("data"), dict) else event

        log.info("VK Play event: channel=%s type=%s", channel, event_type or "unknown")
        log.debug("VK Play event payload: %s", event)

        alert = self._map_event_to_alert(channel, event_type, data, raw=event)
        if alert:
            await self.emit(alert)

    def _map_event_to_alert(
        self,
        channel: str,
        event_type: str,
        data: dict[str, Any],
        raw: dict[str, Any],
    ) -> AlertEvent | None:
        event_type_lower = event_type.lower()
        duration_ms = int(self.config.get("duration_ms", 7000))

        username = self._pick_first(
            data.get("nick"),
            data.get("nickname"),
            data.get("username"),
            data.get("display_name"),
            (data.get("author") or {}).get("nick") if isinstance(data.get("author"), dict) else None,
            (data.get("user") or {}).get("nick") if isinstance(data.get("user"), dict) else None,
            "VK зритель",
        )

        avatar_url = self._pick_first(
            data.get("avatar_url"),
            (data.get("author") or {}).get("avatar_url") if isinstance(data.get("author"), dict) else None,
            (data.get("user") or {}).get("avatar_url") if isinstance(data.get("user"), dict) else None,
            None,
        )

        message = self._extract_message(data)
        amount = self._extract_amount(data)

        if "follow" in event_type_lower:
            return AlertEvent(
                type="follow",
                platform="vk_play",
                title="Новый фоллоу",
                message=message or "Подписался на канал",
                username=username,
                avatar_url=avatar_url,
                duration_ms=duration_ms,
                raw=raw,
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
                raw=raw,
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
                raw=raw,
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
                raw=raw,
            )

        if "donat" in event_type_lower or "donation" in event_type_lower:
            return AlertEvent(
                type="donation",
                platform="vk_play",
                title="Новый донат",
                message=message,
                username=username,
                amount=amount,
                avatar_url=avatar_url,
                duration_ms=duration_ms,
                raw=raw,
            )

        if event_type_lower == "channel_chat_message_send":
            chat_message = data.get("chat_message") if isinstance(data.get("chat_message"), dict) else {}
            message_id = chat_message.get("id")
            if self._is_duplicate_chat_message(message_id):
                log.debug("VK Play: duplicate chat message skipped: %s", message_id)
                return None

            reward_alert = self._extract_reward_alert_from_chatbot(data, raw, duration_ms)
            if reward_alert:
                return reward_alert

            if bool(self.config.get("emit_chat_as_custom", False)):
                author = chat_message.get("author") if isinstance(chat_message.get("author"), dict) else {}
                chat_username = self._pick_first(author.get("nick"), "VK чат")
                chat_avatar = self._pick_first(author.get("avatar_url"), None)
                chat_text = self._extract_message(chat_message)
                if chat_text:
                    return AlertEvent(
                        type="custom",
                        platform="vk_play",
                        title="VK Play чат",
                        message=chat_text,
                        username=chat_username,
                        avatar_url=chat_avatar,
                        duration_ms=duration_ms,
                        raw=raw,
                    )

            return None

        if "point" in event_type_lower or "reward" in event_type_lower:
            reward_title = self._pick_first(
                (data.get("reward") or {}).get("name") if isinstance(data.get("reward"), dict) else None,
                message,
                f"Событие баллов канала: {event_type or 'unknown'}",
            )
            return AlertEvent(
                type="custom",
                platform="vk_play",
                title="Награда VK Play",
                message=reward_title,
                username="VK Play",
                avatar_url=None,
                duration_ms=duration_ms,
                raw=raw,
            )

        if bool(self.config.get("emit_unknown_events", False)):
            return AlertEvent(
                type="custom",
                platform="vk_play",
                title=f"VK Play: {event_type or 'unknown'}",
                message=message or f"Канал: {channel}",
                username=username,
                amount=amount,
                avatar_url=avatar_url,
                duration_ms=duration_ms,
                raw=raw,
            )

        return None

    def _extract_reward_alert_from_chatbot(
        self,
        data: dict[str, Any],
        raw: dict[str, Any],
        duration_ms: int,
    ) -> AlertEvent | None:
        chat_message = data.get("chat_message")
        if not isinstance(chat_message, dict):
            return None

        author = chat_message.get("author")
        if not isinstance(author, dict):
            return None

        if not self._is_chatbot_author(author):
            return None

        parts = chat_message.get("parts")
        if not isinstance(parts, list):
            return None

        text_chunks = self._extract_text_chunks(parts)
        if not text_chunks:
            return None

        reward_name = ""
        user_comment_parts: list[str] = []

        for idx, chunk in enumerate(text_chunks):
            lowered = chunk.lower()
            prefix = "получает награду:"
            if prefix in lowered:
                pos = lowered.find(prefix)
                reward_name = chunk[pos + len(prefix):].strip(" :")
                if idx + 1 < len(text_chunks):
                    user_comment_parts.extend(text_chunks[idx + 1:])
                break

        if not reward_name:
            return None

        reward_name = self._normalize_reward_name(reward_name)

        user_comment = " ".join(part.strip() for part in user_comment_parts if part.strip()).strip()

        rewards_cfg = self.config.get("vk_play_rewards") or {}
        reward_cfg = rewards_cfg.get(reward_name, {}) if isinstance(rewards_cfg, dict) else {}

        if isinstance(reward_cfg, dict) and reward_cfg.get("enabled") is False:
            log.info("VK Play reward disabled in config: %s", reward_name)
            return None

        custom_title = ""
        custom_message = ""

        if isinstance(reward_cfg, dict):
            custom_title = str(reward_cfg.get("title") or "").strip()
            custom_message = str(reward_cfg.get("message") or "").strip()

        title = custom_title or "Награда VK Play"

        if custom_message:
            message = custom_message if not user_comment else f"{custom_message} • {user_comment}"
        else:
            message = reward_name if not user_comment else f"{reward_name} • {user_comment}"

        return AlertEvent(
            type="custom",
            platform="vk_play",
            title=title,
            message=message,
            username="VK Play",
            avatar_url=None,
            duration_ms=duration_ms,
            raw=raw,
        )

    def _normalize_reward_name(self, reward_name: str) -> str:
        text = reward_name.strip()
        text = re.sub(r"(?:\s*[:\-]?\s*за\s+\d+\s*)+$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s{2,}", " ", text).strip()
        text = text.rstrip(" :-")
        return text or reward_name.strip()

    def _is_chatbot_author(self, author: dict[str, Any]) -> bool:
        nick = str(author.get("nick") or "").strip().lower()
        if nick == "chatbot":
            return True

        badges = author.get("badges")
        if isinstance(badges, list):
            for badge in badges:
                if not isinstance(badge, dict):
                    continue
                if str(badge.get("achievement_name") or "").strip().lower() == "internal_chatbot":
                    return True

        return False

    def _is_duplicate_chat_message(self, message_id) -> bool:
        if not message_id:
            return False

        message_id = str(message_id).strip()

        if message_id in self._seen_chat_ids:
            return True

        self._seen_chat_ids.add(message_id)
        self._seen_chat_ids_queue.append(message_id)

        while len(self._seen_chat_ids_queue) > self._seen_chat_ids_limit:
            old_id = self._seen_chat_ids_queue.pop(0)
            self._seen_chat_ids.discard(old_id)

        return False

    def _extract_text_chunks(self, parts: list[dict[str, Any]]) -> list[str]:
        chunks: list[str] = []

        for part in parts:
            if not isinstance(part, dict):
                continue

            text_obj = part.get("text")
            if isinstance(text_obj, dict):
                content = str(text_obj.get("content") or "").replace("\r", "").strip()
                if content:
                    chunks.append(content)

            link_obj = part.get("link")
            if isinstance(link_obj, dict):
                content = str(link_obj.get("content") or link_obj.get("url") or "").strip()
                if content:
                    chunks.append(content)

            mention_obj = part.get("mention")
            if isinstance(mention_obj, dict):
                nick = str(mention_obj.get("nick") or "").strip()
                if nick:
                    chunks.append(f"@{nick}")

        return chunks

    def _extract_message(self, data: dict[str, Any]) -> str:
        direct = self._pick_first(
            data.get("message"),
            data.get("text"),
            data.get("content"),
            data.get("body"),
            data.get("comment"),
            None,
        )
        if direct:
            return direct

        chat_message = data.get("chat_message")
        if isinstance(chat_message, dict):
            return self._extract_message(chat_message)

        parts = data.get("parts")
        if isinstance(parts, list):
            return " ".join(self._extract_text_chunks(parts)).strip()

        return ""

    def _extract_amount(self, data: dict[str, Any]) -> str | None:
        amount = self._pick_first(
            data.get("amount"),
            data.get("sum"),
            data.get("price"),
            data.get("value"),
            data.get("donation_amount"),
            None,
        )
        currency = self._pick_first(
            data.get("currency"),
            data.get("currency_code"),
            data.get("amount_currency"),
            data.get("donation_currency"),
            None,
        )

        if not amount:
            return None

        return f"{amount} {currency}".strip()

    def _pick_first(self, *values: Any) -> str:
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""