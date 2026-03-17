from __future__ import annotations

import asyncio

from models import AlertEvent
from providers.base import BaseProvider


class FakeProvider(BaseProvider):
    name = "fake"

    async def run(self) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(999999)

    async def emit_demo_pack(self) -> None:
        demo_events = [
            AlertEvent(
                type="follow",
                platform="twitch",
                title="Новый фолловер",
                username="Cool_User",
                message="Спасибо за фоллоу!",
            ),
            AlertEvent(
                type="member",
                platform="youtube",
                title="Новый мембер",
                username="YT_Premium",
                message="Добро пожаловать в клуб",
            ),
            AlertEvent(
                type="subscribe",
                platform="trovo",
                title="Новая подписка",
                username="TrovoKnight",
                message="Подписка уровня L1",
            ),
            AlertEvent(
                type="donation",
                platform="donation_alerts",
                title="Новый донат",
                username="Donater",
                amount="250 ₽",
                message="На развитие алертов",
            ),
        ]
        for event in demo_events:
            await self.emit(event)
            await asyncio.sleep(1.2)
