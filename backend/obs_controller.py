from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import obsws_python as obs

log = logging.getLogger(__name__)


@dataclass
class OBSConnectionSettings:
    host: str = "127.0.0.1"
    port: int = 4455
    password: str = ""
    timeout: int = 3


class OBSController:
    def __init__(self) -> None:
        self._client: obs.ReqClient | None = None
        self._settings = OBSConnectionSettings()

    def connect(
        self,
        host: str = "127.0.0.1",
        port: int = 4455,
        password: str = "",
        timeout: int = 3,
    ) -> tuple[bool, str]:
        self.disconnect()

        self._settings = OBSConnectionSettings(
            host=host.strip() or "127.0.0.1",
            port=int(port),
            password=password,
            timeout=int(timeout),
        )

        try:
            self._client = obs.ReqClient(
                host=self._settings.host,
                port=self._settings.port,
                password=self._settings.password,
                timeout=self._settings.timeout,
            )

            version = self.get_version()
            log.info(
                "OBS connected: host=%s port=%s version=%s",
                self._settings.host,
                self._settings.port,
                version.get("obs_version", "unknown"),
            )
            return True, f"OBS подключён: {version.get('obs_version', 'unknown')}"
        except Exception as e:
            self._client = None
            log.exception("OBS connect failed")
            return False, f"Не удалось подключиться к OBS: {e}"

    def disconnect(self) -> None:
        self._client = None

    def is_connected(self) -> bool:
        return self._client is not None

    def _require_client(self) -> obs.ReqClient:
        if self._client is None:
            raise RuntimeError("OBS не подключён")
        return self._client

    def get_version(self) -> dict[str, Any]:
        client = self._require_client()
        data = client.get_version()
        return {
            "obs_version": getattr(data, "obs_version", ""),
            "obs_websocket_version": getattr(data, "obs_web_socket_version", ""),
        }

    def get_scene_names(self) -> list[str]:
        client = self._require_client()
        data = client.get_scene_list()

        scenes = getattr(data, "scenes", []) or []
        result: list[str] = []

        for scene in scenes:
            if isinstance(scene, dict):
                name = scene.get("sceneName") or scene.get("scene_name")
            else:
                name = getattr(scene, "sceneName", None) or getattr(scene, "scene_name", None)

            if name:
                result.append(str(name))

        return result

    def get_current_program_scene(self) -> str:
        client = self._require_client()
        data = client.get_scene_list()

        current = (
            getattr(data, "current_program_scene_name", None)
            or getattr(data, "currentProgramSceneName", None)
            or ""
        )
        return str(current)

    def switch_scene(self, scene_name: str) -> tuple[bool, str]:
        client = self._require_client()
        try:
            client.set_current_program_scene(scene_name)
            return True, f"Сцена переключена: {scene_name}"
        except Exception as e:
            return False, f"Не удалось переключить сцену: {e}"

    def get_scene_item_id(self, scene_name: str, source_name: str) -> int | None:
        client = self._require_client()
        try:
            data = client.get_scene_item_id(scene_name=scene_name, source_name=source_name)
            item_id = getattr(data, "scene_item_id", None) or getattr(data, "sceneItemId", None)
            return int(item_id) if item_id is not None else None
        except Exception:
            return None

    def set_source_enabled(self, scene_name: str, source_name: str, enabled: bool) -> tuple[bool, str]:
        client = self._require_client()

        item_id = self.get_scene_item_id(scene_name, source_name)
        if item_id is None:
            return False, f"Источник не найден: {scene_name} / {source_name}"

        try:
            client.set_scene_item_enabled(
                scene_name=scene_name,
                item_id=item_id,
                enabled=bool(enabled),
            )
            return True, f"{'Показан' if enabled else 'Скрыт'} источник: {source_name}"
        except Exception as e:
            return False, f"Не удалось изменить видимость источника: {e}"

    def show_source(self, scene_name: str, source_name: str) -> tuple[bool, str]:
        return self.set_source_enabled(scene_name, source_name, True)

    def hide_source(self, scene_name: str, source_name: str) -> tuple[bool, str]:
        return self.set_source_enabled(scene_name, source_name, False)