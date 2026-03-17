from __future__ import annotations

import asyncio
import logging

from providers.base import BaseProvider

log = logging.getLogger(__name__)


class TwitchProvider(BaseProvider):
    name = "twitch"

    async def run(self) -> None:
        """
        Здесь должна быть реальная интеграция с Twitch EventSub.

        Что сюда подключать:
        - OAuth приложения
        - создание подписок EventSub
        - приём событий follow / subscribe / resubscribe / gift_sub / cheer / raid
        - преобразование payload в общий AlertEvent

        Почему это вынесено отдельно:
        - чтобы движок алертов не зависел от конкретной платформы
        - чтобы ты мог менять стиль алертов, не трогая интеграции
        """
        log.info("Twitch provider пока в каркасе. Движок готов, интеграцию добавим следующим этапом.")
        while not self._stop.is_set():
            await asyncio.sleep(3600)
