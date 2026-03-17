from __future__ import annotations

import asyncio
import logging

from providers.base import BaseProvider

log = logging.getLogger(__name__)


class TrovoProvider(BaseProvider):
    name = "trovo"

    async def run(self) -> None:
        """
        Каркас для Trovo:
        - websocket чата для spell/gift/chat событий,
        - периодический опрос followers и subscriptions,
        - дедупликация по user_id и timestamps,
        - перевод в общий формат AlertEvent.
        """
        log.info("Trovo provider пока в каркасе. Готов к доработке под followers/subscriptions/chat gifts.")
        while not self._stop.is_set():
            await asyncio.sleep(3600)
