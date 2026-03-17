from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path("config.yaml")


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        example = path.with_name("config.example.yaml")
        if example.exists():
            return yaml.safe_load(example.read_text(encoding="utf-8"))
        raise FileNotFoundError(
            f"Не найден {path}. Скопируй config.example.yaml в config.yaml и настрой его."
        )
    return yaml.safe_load(path.read_text(encoding="utf-8"))
