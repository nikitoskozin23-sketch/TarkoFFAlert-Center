from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


class ConfigManager:
    DEFAULTS: dict[str, Any] = {
        "show_site_ads": False,
        "ad_title": "Скоро запуск сайта!",
        "ad_line2": "TarkoFFchanin.pro",
        "ad_line3": "Следи за анонсами",
        "music_volume": "0.35",
        "tts_volume": "1.00",
        "tts_voice": "default",
    }

    def __init__(self, settings_path: str | Path) -> None:
        self.settings_path = Path(settings_path)
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)

    def _defaults(self) -> dict[str, Any]:
        return deepcopy(self.DEFAULTS)

    def load(self) -> dict[str, Any]:
        defaults = self._defaults()

        if not self.settings_path.exists():
            self.save(defaults)
            return defaults

        try:
            raw = self.settings_path.read_text(encoding="utf-8").strip()
            if not raw:
                self.save(defaults)
                return defaults

            loaded = json.loads(raw)
            if not isinstance(loaded, dict):
                self._backup_broken_file()
                self.save(defaults)
                return defaults

            merged = defaults | loaded
            return merged

        except Exception:
            self._backup_broken_file()
            self.save(defaults)
            return defaults

    def save(self, data: dict[str, Any]) -> dict[str, Any]:
        merged = self._defaults() | dict(data)
        self.settings_path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return merged

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.load()
        current.update(patch)
        return self.save(current)

    def reset(self) -> dict[str, Any]:
        defaults = self._defaults()
        self.save(defaults)
        return defaults

    def _backup_broken_file(self) -> None:
        if not self.settings_path.exists():
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.settings_path.with_name(
            f"{self.settings_path.stem}.broken_{timestamp}{self.settings_path.suffix}"
        )

        try:
            backup_path.write_text(
                self.settings_path.read_text(encoding="utf-8", errors="replace"),
                encoding="utf-8",
            )
        except Exception:
            pass