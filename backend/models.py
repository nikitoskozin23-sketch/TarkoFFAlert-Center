from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


AlertType = Literal[
    "follow",
    "subscribe",
    "resubscribe",
    "gift_sub",
    "donation",
    "superchat",
    "sticker",
    "member",
    "raid",
    "cheer",
    "custom",
]

PlatformType = Literal[
    "twitch",
    "youtube",
    "trovo",
    "vk_play",
    "donation_alerts",
    "system",
]


class AlertEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: AlertType
    platform: PlatformType
    title: str
    message: str = ""
    username: str = ""
    amount: str | None = None
    avatar_url: str | None = None
    sound_url: str | None = None
    image_url: str | None = None
    duration_ms: int = 7000
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    raw: dict[str, Any] = Field(default_factory=dict)


class TestAlertRequest(BaseModel):
    type: AlertType = "custom"
    platform: PlatformType = "system"
    title: str = "Тестовое оповещение"
    message: str = "Проверка анимации и очереди"
    username: str = "viewer_01"
    amount: str | None = None
    duration_ms: int = 7000
    image_url: str | None = None
    sound_url: str | None = None
