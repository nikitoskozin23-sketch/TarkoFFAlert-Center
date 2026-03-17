from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
import websockets

from models import AlertEvent
from providers.base import BaseProvider

log = logging.getLogger(__name__)


class DonationAlertsProvider(BaseProvider):
    name = "donation_alerts"

    WS_URL = "wss://centrifugo.donationalerts.com/connection/websocket"
    API_BASE = "https://www.donationalerts.com/api/v1"

    def __init__(self, config: dict[str, Any], context):
        super().__init__(config, context)
        self._seen_donation_ids = set()
        self._seen_donation_ids_queue = []
        self._seen_donation_ids_limit = 500

    async def run(self) -> None:
        access_token = str(self.config.get("access_token", "")).strip()
        if not access_token:
            log.warning("DonationAlerts включён, но access_token пустой в config.yaml")
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
                log.exception("DonationAlerts provider error: %s", exc)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30)

    async def _run_once(self, access_token: str) -> None:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(headers=headers, timeout=20.0) as client:
            profile = await self._fetch_profile(client)
            user_id = str(self.config.get("user_id") or profile["id"])
            socket_connection_token = profile["socket_connection_token"]

            channel_name = f"$alerts:donation_{user_id}"
            log.info("DonationAlerts: подключаем канал %s", channel_name)

            async with websockets.connect(
                self.WS_URL,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=10,
                max_size=2**20,
            ) as ws:
                await ws.send(json.dumps({"params": {"token": socket_connection_token}, "id": 1}))
                client_id = await self._receive_client_id(ws)
                log.info("DonationAlerts: websocket connected, client_id=%s", client_id)

                subscribe_token = await self._fetch_channel_token(client, client_id, channel_name)
                await ws.send(
                    json.dumps(
                        {
                            "params": {"channel": channel_name, "token": subscribe_token},
                            "method": 1,
                            "id": 2,
                        }
                    )
                )
                log.info("DonationAlerts: подписка на %s отправлена", channel_name)

                while not self._stop.is_set():
                    raw_message = await ws.recv()
                    for payload in self._decode_ws_payload(raw_message):
                        await self._handle_ws_payload(payload)

    async def _fetch_profile(self, client: httpx.AsyncClient) -> dict[str, Any]:
        response = await client.get(f"{self.API_BASE}/user/oauth")
        response.raise_for_status()
        data = response.json().get("data") or {}
        if not data.get("socket_connection_token"):
            raise RuntimeError(
                "DonationAlerts не вернул socket_connection_token. Проверь access token и scope oauth-user-show."
            )
        if not data.get("id"):
            raise RuntimeError("DonationAlerts не вернул user id в /user/oauth")
        return data

    async def _fetch_channel_token(
        self,
        client: httpx.AsyncClient,
        client_id: str,
        channel_name: str,
    ) -> str:
        response = await client.post(
            f"{self.API_BASE}/centrifuge/subscribe",
            json={"channels": [channel_name], "client": client_id},
        )
        response.raise_for_status()
        channels = response.json().get("channels") or []
        for item in channels:
            if item.get("channel") == channel_name and item.get("token"):
                return str(item["token"])
        raise RuntimeError(
            "DonationAlerts не вернул токен канала. Проверь scope oauth-donation-subscribe и user_id."
        )

    async def _receive_client_id(self, ws) -> str:
        raw_message = await ws.recv()
        for payload in self._decode_ws_payload(raw_message):
            result = payload.get("result") or {}
            client_id = result.get("client")
            if client_id:
                return str(client_id)
        raise RuntimeError("Не удалось получить client_id от Centrifugo")

    def _decode_ws_payload(self, raw_message: Any) -> list[dict[str, Any]]:
        if isinstance(raw_message, bytes):
            raw_message = raw_message.decode("utf-8", errors="ignore")

        parts = [part.strip() for part in str(raw_message).splitlines() if part.strip()]
        payloads: list[dict[str, Any]] = []

        for part in parts:
            try:
                data = json.loads(part)
            except json.JSONDecodeError:
                log.debug("DonationAlerts: не удалось распарсить websocket payload: %r", part)
                continue

            if isinstance(data, list):
                payloads.extend(item for item in data if isinstance(item, dict))
            elif isinstance(data, dict):
                payloads.append(data)

        return payloads

    async def _handle_ws_payload(self, payload: dict[str, Any]) -> None:
        result = payload.get("result") or {}
        if result.get("type") == 1 and result.get("channel"):
            log.info("DonationAlerts: подтверждена подписка на %s", result.get("channel"))
            return

        candidates: list[dict[str, Any]] = []

        push = payload.get("push")
        if isinstance(push, dict):
            pub = push.get("pub")
            if isinstance(pub, dict):
                candidates.append(pub)
            if isinstance(push.get("data"), dict):
                candidates.append(push)

        if isinstance(result, dict):
            pub = result.get("publication")
            if isinstance(pub, dict):
                candidates.append(pub)
            if isinstance(result.get("publications"), list):
                candidates.extend(item for item in result["publications"] if isinstance(item, dict))
            if isinstance(result.get("data"), dict) and result.get("channel"):
                candidates.append(result)

        if isinstance(payload.get("pub"), dict):
            candidates.append(payload["pub"])

        for candidate in candidates:
            donation = self._extract_donation(candidate)
            if donation:
                donation_id = str(donation.get("id") or "").strip()
                if self._is_duplicate_donation(donation_id):
                    log.debug("DonationAlerts: duplicate donation skipped id=%s", donation_id)
                    return

                await self._emit_donation(donation)
                return

        if payload.get("id") in (1, 2):
            return

        log.debug("DonationAlerts: неизвестный websocket payload: %s", payload)

    def _extract_donation(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        data = payload

        for _ in range(3):
            if not isinstance(data, dict):
                return None

            inner = data.get("data")
            if not isinstance(inner, dict):
                break

            if any(k in inner for k in ("amount", "currency", "username", "name", "message", "id")):
                data = inner
                break

            data = inner

        if not isinstance(data, dict):
            return None

        name = str(data.get("name") or "")
        username = str(data.get("username") or "")
        amount = data.get("amount")

        looks_like_donation = (
            name == "donation"
            or "currency" in data
            or amount is not None
            or bool(username)
            or bool(data.get("message"))
        )
        if not looks_like_donation:
            return None

        donation_id = str(data.get("id") or "")
        if donation_id:
            log.debug("DonationAlerts: получен donation id=%s", donation_id)

        log.info("DonationAlerts: пойман донат payload=%s", data)
        return data

    async def _emit_donation(self, data: dict[str, Any]) -> None:
        username = str(data.get("username") or data.get("name") or "Аноним")
        message = str(data.get("message") or "")
        amount = self._format_amount(data.get("amount"), data.get("currency"))

        event = AlertEvent(
            type="donation",
            platform="donation_alerts",
            title="Новый донат",
            message=message,
            username=username,
            amount=amount,
            duration_ms=int(self.config.get("duration_ms", 7000)),
            raw=data,
        )
        log.info("DonationAlerts: отправляем alert username=%s amount=%s", username, amount)
        await self.emit(event)

    def _is_duplicate_donation(self, donation_id) -> bool:
        if not donation_id:
            return False

        donation_id = str(donation_id).strip()

        if donation_id in self._seen_donation_ids:
            return True

        self._seen_donation_ids.add(donation_id)
        self._seen_donation_ids_queue.append(donation_id)

        while len(self._seen_donation_ids_queue) > self._seen_donation_ids_limit:
            old_id = self._seen_donation_ids_queue.pop(0)
            self._seen_donation_ids.discard(old_id)

        return False

    def _format_amount(self, amount: Any, currency: Any) -> str | None:
        if amount in (None, ""):
            return None

        amount_text = str(amount)
        try:
            value = Decimal(amount_text)
            amount_text = f"{value.normalize()}"
            if amount_text.endswith(".0"):
                amount_text = amount_text[:-2]
        except (InvalidOperation, ValueError):
            pass

        currency_text = str(currency or "").strip()
        return f"{amount_text} {currency_text}".strip()