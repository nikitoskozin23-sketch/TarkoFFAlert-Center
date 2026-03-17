from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any


class QueueManager:
    def __init__(self, settings: dict[str, Any], logs: list[str]) -> None:
        self.queue: deque[dict[str, Any]] = deque()
        self.current_alert: dict[str, Any] | None = None
        self.phase = "idle"
        self.settings = settings
        self.logs = logs
        self.lock = threading.Lock()
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def add_log(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.logs.append(f"[{stamp}] {text}")
        if len(self.logs) > 1000:
            del self.logs[:200]

    def add_alert(self, donor: str, amount: str, message: str) -> None:
        with self.lock:
            self.queue.append({
                "donor": donor,
                "amount": amount,
                "message": message,
            })
        self.add_log(f"Добавлен алерт в очередь: {donor} / {amount}")

    def state(self) -> dict[str, Any]:
        with self.lock:
            return {
                "current_alert": self.current_alert,
                "phase": self.phase,
                "queue_size": len(self.queue),
                "ad_enabled": bool(self.settings.get("ad_enabled", False)),
                "ad_text": self.settings.get("ad_text", "Скоро запуск сайта"),
                "ad_subtext": self.settings.get("ad_subtext", "TarkoFFchanin.pro"),
                "ad_follow": self.settings.get("ad_follow", "Следи за анонсами"),
            }

    def _run(self) -> None:
        while True:
            next_alert = None
            with self.lock:
                if self.current_alert is None and self.queue:
                    next_alert = self.queue.popleft()
                    self.current_alert = next_alert
                    self.phase = "show"

            if next_alert:
                self.add_log("Фаза SHOW: показываем алерт")
                time.sleep(float(self.settings.get("show_seconds", 4)))

                with self.lock:
                    self.phase = "music"
                self.add_log("Фаза MUSIC: тут позже подключается реальная музыка")
                time.sleep(float(self.settings.get("music_seconds", 2)))

                with self.lock:
                    self.phase = "tts"
                self.add_log("Фаза TTS: тут позже подключается реальная озвучка")
                time.sleep(float(self.settings.get("tts_seconds", 4)))

                with self.lock:
                    self.current_alert = None
                    self.phase = "idle"
                self.add_log("Алерт завершён")
            else:
                time.sleep(0.2)
