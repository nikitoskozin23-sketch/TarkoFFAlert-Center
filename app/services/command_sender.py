from __future__ import annotations

from typing import Any

import requests


class CommandSender:
    def __init__(self, base_url: str = "http://127.0.0.1:8765") -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.trust_env = False

    def _get(self, path: str) -> dict[str, Any]:
        r = self.session.get(f"{self.base_url}{path}", timeout=2.5)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        r = self.session.post(f"{self.base_url}{path}", json=payload, timeout=3.5)
        r.raise_for_status()
        return r.json()

    def health(self) -> dict[str, Any]:
        return self._get("/api/health")

    def settings(self) -> dict[str, Any]:
        return self._get("/api/settings")

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/api/settings", payload)

    def toggle_ad(self, enabled: bool) -> dict[str, Any]:
        return self._post("/api/toggle-ad", {"enabled": enabled})

    def test_alert(self, donor: str, amount: str, message: str) -> dict[str, Any]:
        payload = {
            "provider": "donation_alerts",
            "event_type": "donation",
            "title": "Новый донат",
            "donor": donor,
            "amount": amount,
            "message": message,
        }
        return self._post("/api/test", payload)