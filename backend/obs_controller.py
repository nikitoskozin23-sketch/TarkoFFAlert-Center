from __future__ import annotations

import logging
from typing import Any

try:
    import obsws_python as obsws
except Exception:  # pragma: no cover
    obsws = None


log = logging.getLogger("obs_controller")


class OBSController:
    def __init__(self) -> None:
        self.client: Any | None = None
        self.host = "127.0.0.1"
        self.port = 4455
        self.password = ""

    def is_connected(self) -> bool:
        return self.client is not None

    def connect(self, host: str, port: int, password: str) -> tuple[bool, str]:
        if obsws is None:
            return False, "Не установлен пакет obsws_python"

        try:
            self.disconnect()

            self.host = host
            self.port = int(port)
            self.password = password

            self.client = obsws.ReqClient(
                host=self.host,
                port=self.port,
                password=self.password,
                timeout=5,
            )

            version = self.get_version()
            obs_version = version.get("obs_version", "unknown")
            return True, f"OBS подключён: {obs_version}"
        except Exception as e:
            self.client = None
            return False, f"Не удалось подключиться к OBS: {e}"

    def disconnect(self) -> None:
        try:
            if self.client is not None:
                base = getattr(self.client, "base_client", None)
                if base is not None and hasattr(base, "disconnect"):
                    base.disconnect()
        except Exception:
            pass
        finally:
            self.client = None

    def get_version(self) -> dict[str, Any]:
        if not self.is_connected():
            return {}

        response = self.client.get_version()

        return {
            "obs_version": str(
                getattr(response, "obs_version", None)
                or getattr(response, "obsVersion", None)
                or ""
            ),
            "obs_websocket_version": str(
                getattr(response, "obs_web_socket_version", None)
                or getattr(response, "obs_websocket_version", None)
                or getattr(response, "obsWebSocketVersion", None)
                or ""
            ),
        }

    def get_scene_names(self) -> list[str]:
        if not self.is_connected():
            return []

        response = self.client.get_scene_list()

        raw_scenes = getattr(response, "scenes", None)
        if raw_scenes is None and isinstance(response, dict):
            raw_scenes = response.get("scenes")

        result: list[str] = []
        seen: set[str] = set()

        for scene in raw_scenes or []:
            if isinstance(scene, dict):
                name = str(
                    scene.get("sceneName")
                    or scene.get("scene_name")
                    or ""
                ).strip()
            else:
                name = str(
                    getattr(scene, "sceneName", "")
                    or getattr(scene, "scene_name", "")
                    or ""
                ).strip()

            if name and name not in seen:
                seen.add(name)
                result.append(name)

        return result

    def get_current_program_scene(self) -> str:
        if not self.is_connected():
            return ""

        response = self.client.get_current_program_scene()

        return str(
            getattr(response, "current_program_scene_name", None)
            or getattr(response, "currentProgramSceneName", None)
            or ""
        ).strip()

    def switch_scene(self, scene_name: str) -> tuple[bool, str]:
        if not self.is_connected():
            return False, "OBS не подключён"

        scene_name = str(scene_name or "").strip()
        if not scene_name:
            return False, "Не указано имя сцены"

        try:
            self.client.set_current_program_scene(scene_name)
            return True, f"Сцена переключена: {scene_name}"
        except Exception as e:
            return False, f"Не удалось переключить сцену: {e}"

    def _get_scene_item_id(self, scene_name: str, source_name: str) -> int | None:
        if not self.is_connected():
            return None

        try:
            response = self.client.get_scene_item_id(scene_name, source_name)
            item_id = (
                getattr(response, "scene_item_id", None)
                or getattr(response, "sceneItemId", None)
            )
            if item_id is None and isinstance(response, dict):
                item_id = response.get("scene_item_id") or response.get("sceneItemId")

            return int(item_id) if item_id is not None else None
        except Exception:
            return None

    def show_source(self, scene_name: str, source_name: str) -> tuple[bool, str]:
        if not self.is_connected():
            return False, "OBS не подключён"

        scene_name = str(scene_name or "").strip()
        source_name = str(source_name or "").strip()

        if not scene_name:
            return False, "Не указана сцена"
        if not source_name:
            return False, "Не указано имя источника"

        try:
            item_id = self._get_scene_item_id(scene_name, source_name)
            if item_id is None:
                return False, f"Источник не найден: {source_name} (сцена: {scene_name})"

            self.client.set_scene_item_enabled(scene_name, item_id, True)
            return True, f"Источник показан: {source_name}"
        except Exception as e:
            return False, f"Не удалось изменить видимость источника: {e}"

    def hide_source(self, scene_name: str, source_name: str) -> tuple[bool, str]:
        if not self.is_connected():
            return False, "OBS не подключён"

        scene_name = str(scene_name or "").strip()
        source_name = str(source_name or "").strip()

        if not scene_name:
            return False, "Не указана сцена"
        if not source_name:
            return False, "Не указано имя источника"

        try:
            item_id = self._get_scene_item_id(scene_name, source_name)
            if item_id is None:
                return False, f"Источник не найден: {source_name} (сцена: {scene_name})"

            self.client.set_scene_item_enabled(scene_name, item_id, False)
            return True, f"Источник скрыт: {source_name}"
        except Exception as e:
            return False, f"Не удалось изменить видимость источника: {e}"

    def get_scene_items(self, scene_name: str) -> list[str]:
        if not self.is_connected():
            return []

        scene_name = str(scene_name or "").strip()
        if not scene_name:
            return []

        response = self.client.get_scene_item_list(scene_name)

        raw_items = getattr(response, "scene_items", None)
        if raw_items is None:
            raw_items = getattr(response, "sceneItems", None)
        if raw_items is None and isinstance(response, dict):
            raw_items = response.get("scene_items") or response.get("sceneItems")

        result: list[str] = []
        seen: set[str] = set()

        for item in raw_items or []:
            if isinstance(item, dict):
                name = str(
                    item.get("sourceName")
                    or item.get("source_name")
                    or ""
                ).strip()
            else:
                name = str(
                    getattr(item, "sourceName", "")
                    or getattr(item, "source_name", "")
                    or ""
                ).strip()

            if name and name not in seen:
                seen.add(name)
                result.append(name)

        return result