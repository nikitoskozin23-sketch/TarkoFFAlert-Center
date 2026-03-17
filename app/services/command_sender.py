from __future__ import annotations

from typing import Any

import requests


class CommandSender:
    def __init__(self, base_url: str = "http://127.0.0.1:8765") -> None:
        self.base_url = base_url.rstrip("/")

    def _get(self, path: str) -> dict[str, Any]:
        r = requests.get(f"{self.base_url}{path}", timeout=3.0)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        r = requests.post(f"{self.base_url}{path}", json=payload, timeout=5.0)
        r.raise_for_status()
        return r.json()

    def health(self) -> dict[str, Any]:
        return self._get("/api/health")

    def history(self) -> list[dict[str, Any]]:
        return self._get("/api/history")

    def settings(self) -> dict[str, Any]:
        return self._get("/api/settings")

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/api/settings", payload)

    def toggle_ad(self, enabled: bool) -> dict[str, Any]:
        return self._post("/api/toggle-ad", {"enabled": enabled})

    def test_alert(
        self,
        donor: str = "TarkoFF Supporter",
        amount: str = "250",
        message: str = "Тест из GUI",
        provider: str = "donation_alerts",
        event_type: str = "donation",
        title: str = "Новый донат",
    ) -> dict[str, Any]:
        return self._post(
            "/api/test",
            {
                "provider": provider,
                "event_type": event_type,
                "title": title,
                "donor": donor,
                "amount": amount,
                "message": message,
            },
        )

    def obs_status(self) -> dict[str, Any]:
        return self._get("/api/obs/status")

    def obs_connect(
        self,
        host: str = "127.0.0.1",
        port: int = 4455,
        password: str = "",
    ) -> dict[str, Any]:
        return self._post(
            "/api/obs/connect",
            {
                "host": host,
                "port": int(port),
                "password": password,
            },
        )

    def obs_show_source(self, scene_name: str, source_name: str) -> dict[str, Any]:
        return self._post(
            "/api/obs/show-source",
            {
                "scene_name": scene_name,
                "source_name": source_name,
            },
        )

    def obs_hide_source(self, scene_name: str, source_name: str) -> dict[str, Any]:
        return self._post(
            "/api/obs/hide-source",
            {
                "scene_name": scene_name,
                "source_name": source_name,
            },
        )

    def obs_show_qr_temp(
        self,
        scene_name: str = "2",
        source_name: str = "TarkoFFchanin QR Donate Premium v2",
        duration_sec: int = 15,
    ) -> dict[str, Any]:
        return self._post(
            "/api/obs/show-qr-temp",
            {
                "scene_name": scene_name,
                "source_name": source_name,
                "duration_sec": int(duration_sec),
            },
        )