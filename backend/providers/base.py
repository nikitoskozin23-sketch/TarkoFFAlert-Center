from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

from models import AlertEvent

log = logging.getLogger(__name__)


class ProviderContext:
    def __init__(self, emit_alert):
        self.emit_alert = emit_alert


class BaseProvider(ABC):
    name = "base"

    def __init__(self, config: dict[str, Any], context: ProviderContext):
        self.config = config
        self.context = context
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("enabled", False))

    async def start(self) -> None:
        if not self.enabled:
            log.info("Provider %s отключён в config.yaml", self.name)
            return
        log.info("Запуск provider: %s", self.name)
        self._task = asyncio.create_task(self.run(), name=f"provider:{self.name}")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def emit(self, event: AlertEvent) -> None:
        await self.context.emit_alert(event)

    @abstractmethod
    async def run(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError
