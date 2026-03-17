from __future__ import annotations

import inspect
import webbrowser
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QRegularExpression, QTimer
from PySide6.QtGui import QRegularExpressionValidator, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.backend_manager import BackendManager
from app.services.config_manager import ConfigManager

try:
    from app.services.command_sender import CommandSender  # type: ignore
except Exception:
    CommandSender = None  # type: ignore


class MainWindow(QMainWindow):
    TTS_VOICE_PRESETS = [
        ("default — системный", "default"),
        ("Dmitry — ru-RU-DmitryNeural (мужской)", "ru-RU-DmitryNeural"),
        ("Svetlana — ru-RU-SvetlanaNeural (женский)", "ru-RU-SvetlanaNeural"),
    ]

    PROVIDERS = [
        ("twitch", "Twitch"),
        ("youtube", "YouTube"),
        ("trovo", "Trovo"),
        ("donation_alerts", "DonationAlerts"),
        ("vk_play", "VK Play"),
    ]

    def __init__(self) -> None:
        super().__init__()

        self.project_root = Path(__file__).resolve().parents[1]
        self.config_dir = self.project_root / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.config_dir / "settings.json"

        self.backend = BackendManager()
        self.config_manager = ConfigManager(self.settings_path)
        self.command_sender = self._create_command_sender()

        self._last_logs_text = ""
        self._current_state = "offline"
        self._synced_from_backend = False
        self.provider_status_labels: dict[str, QLabel] = {}

        self.setWindowTitle("TarkoFF Stream Center v0.1")
        self.resize(1220, 940)

        self.notice_timer = QTimer(self)
        self.notice_timer.setSingleShot(True)
        self.notice_timer.timeout.connect(self._clear_notice)

        self._build_ui()
        self._load_settings_into_form()
        self.refresh_everything()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(1000)
        self.refresh_timer.timeout.connect(self.refresh_everything)
        self.refresh_timer.start()

    # -------------------------------------------------------------------------
    # UI
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        self.status_label = QLabel("Статус: offline")
        self.status_label.setStyleSheet(
            "font-size: 28px; font-weight: 700; color: #d32f2f;"
        )
        root.addWidget(self.status_label)

        top_buttons = QHBoxLayout()
        top_buttons.setSpacing(10)

        self.btn_start = QPushButton("Запустить backend")
        self.btn_stop = QPushButton("Остановить backend")
        self.btn_restart = QPushButton("Перезапустить backend")
        self.btn_overlay = QPushButton("Открыть overlay")
        self.btn_control = QPushButton("Открыть control")
        self.btn_refresh = QPushButton("Обновить")

        for btn in (
            self.btn_start,
            self.btn_stop,
            self.btn_restart,
            self.btn_overlay,
            self.btn_control,
            self.btn_refresh,
        ):
            btn.setMinimumHeight(38)
            top_buttons.addWidget(btn)

        root.addLayout(top_buttons)

        self.notice_label = QLabel("")
        self.notice_label.setMinimumHeight(34)
        self.notice_label.setWordWrap(True)
        self.notice_label.hide()
        root.addWidget(self.notice_label)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(QTabWidget.North)

        self.tab_alerts = self._build_alerts_tab()
        self.tab_settings = self._build_settings_tab()
        self.tab_logs = self._build_logs_tab()

        self.tabs.addTab(self.tab_alerts, "Алерты")
        self.tabs.addTab(self.tab_settings, "Настройки")
        self.tabs.addTab(self.tab_logs, "Логи")

        root.addWidget(self.tabs, 1)

        self.btn_start.clicked.connect(self.on_start_backend)
        self.btn_stop.clicked.connect(self.on_stop_backend)
        self.btn_restart.clicked.connect(self.on_restart_backend)
        self.btn_overlay.clicked.connect(self.on_open_overlay)
        self.btn_control.clicked.connect(self.on_open_control)
        self.btn_refresh.clicked.connect(self.refresh_everything)

        self.btn_send_test_alert.clicked.connect(self.on_send_test_alert)
        self.btn_save_settings.clicked.connect(self.on_save_settings)
        self.btn_apply_ads.clicked.connect(self.on_apply_ads)
        self.btn_copy_log.clicked.connect(self.on_copy_log)
        self.btn_clear_log.clicked.connect(self.on_clear_log)

    def _build_alerts_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(12)

        layout.addWidget(self._build_providers_group())
        layout.addWidget(self._build_test_group())

        self.info_box = QTextEdit()
        self.info_box.setReadOnly(True)
        self.info_box.setFixedHeight(150)
        self.info_box.setPlainText(
            "Что здесь можно делать:\n\n"
            "• отправлять тестовый донат прямо из GUI\n"
            "• быстро проверить звук, TTS и overlay\n"
            "• запускать overlay/control из верхней панели\n\n"
            "Рекомендуемый порядок:\n"
            "1. Запусти backend\n"
            "2. Открой overlay\n"
            "3. Отправь тестовый донат\n"
            "4. Проверь звук, голос и отображение"
        )
        layout.addWidget(self.info_box)

        layout.addStretch(1)
        return page

    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(12)

        layout.addWidget(self._build_settings_group())
        layout.addStretch(1)
        return page

    def _build_logs_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(12)

        logs_group = QGroupBox("Логи backend")
        logs_layout = QVBoxLayout(logs_group)

        logs_tools = QHBoxLayout()
        logs_tools.addStretch()

        self.btn_copy_log = QPushButton("Скопировать лог")
        self.btn_clear_log = QPushButton("Очистить лог")
        self.btn_copy_log.setMinimumHeight(34)
        self.btn_clear_log.setMinimumHeight(34)

        logs_tools.addWidget(self.btn_copy_log)
        logs_tools.addWidget(self.btn_clear_log)
        logs_layout.addLayout(logs_tools)

        self.logs_box = QPlainTextEdit()
        self.logs_box.setReadOnly(True)
        self.logs_box.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.logs_box.setMinimumHeight(540)
        logs_layout.addWidget(self.logs_box)

        layout.addWidget(logs_group)
        return page

    def _build_providers_group(self) -> QGroupBox:
        box = QGroupBox("Провайдеры")
        layout = QGridLayout(box)
        layout.setHorizontalSpacing(18)
        layout.setVerticalSpacing(12)

        for idx, (key, title) in enumerate(self.PROVIDERS):
            name_label = QLabel(title)
            name_label.setStyleSheet("font-size: 14px; font-weight: 700; color: #e5e7eb;")

            status_label = QLabel("")
            status_label.setMinimumWidth(130)

            row = idx // 2
            col = (idx % 2) * 2

            layout.addWidget(name_label, row, col)
            layout.addWidget(status_label, row, col + 1)

            self.provider_status_labels[key] = status_label
            self._set_provider_status(key, "offline")

        return box

    def _build_test_group(self) -> QGroupBox:
        box = QGroupBox("Тестовый алерт")
        layout = QGridLayout(box)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(12)

        self.input_sender = QLineEdit("TarkoFF Supporter")
        self.input_amount = QLineEdit("250")
        self.input_message = QLineEdit("Скоро запуск сайта! Ждём TarkoFFchanin.pro")

        layout.addWidget(QLabel("От кого:"), 0, 0)
        layout.addWidget(self.input_sender, 0, 1)

        layout.addWidget(QLabel("Сумма:"), 1, 0)
        layout.addWidget(self.input_amount, 1, 1)

        layout.addWidget(QLabel("Сообщение:"), 2, 0)
        layout.addWidget(self.input_message, 2, 1)

        self.btn_send_test_alert = QPushButton("Отправить тестовый донат")
        self.btn_send_test_alert.setMinimumHeight(38)
        layout.addWidget(self.btn_send_test_alert, 3, 0, 1, 2)

        layout.setRowStretch(4, 1)
        return box

    def _build_settings_group(self) -> QGroupBox:
        box = QGroupBox("Реклама сайта / настройки")
        layout = QGridLayout(box)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(12)

        self.chk_show_ads = QCheckBox("Показывать рекламу сайта")

        self.input_ad_title = QLineEdit()
        self.input_ad_line2 = QLineEdit()
        self.input_ad_line3 = QLineEdit()
        self.input_music_volume = QLineEdit()
        self.input_tts_volume = QLineEdit()

        volume_regex = QRegularExpression(r"^$|^(0([.,]\d{0,2})?|1([.,]0{0,2})?)$")
        volume_validator = QRegularExpressionValidator(volume_regex, self)

        self.input_music_volume.setValidator(volume_validator)
        self.input_tts_volume.setValidator(volume_validator)

        self.input_music_volume.setPlaceholderText("0.00 - 1.00")
        self.input_tts_volume.setPlaceholderText("0.00 - 1.00")

        self.input_music_volume.editingFinished.connect(self._apply_volume_formatting)
        self.input_tts_volume.editingFinished.connect(self._apply_volume_formatting)

        self.input_tts_voice = QComboBox()
        self.input_tts_voice.setEditable(True)
        self._populate_tts_voices()

        row = 0
        layout.addWidget(self.chk_show_ads, row, 0, 1, 2)
        row += 1

        layout.addWidget(QLabel("Заголовок:"), row, 0)
        layout.addWidget(self.input_ad_title, row, 1)
        row += 1

        layout.addWidget(QLabel("Вторая строка:"), row, 0)
        layout.addWidget(self.input_ad_line2, row, 1)
        row += 1

        layout.addWidget(QLabel("Третья строка:"), row, 0)
        layout.addWidget(self.input_ad_line3, row, 1)
        row += 1

        layout.addWidget(QLabel("Громкость музыки:"), row, 0)
        layout.addWidget(self.input_music_volume, row, 1)
        row += 1

        layout.addWidget(QLabel("Громкость TTS:"), row, 0)
        layout.addWidget(self.input_tts_volume, row, 1)
        row += 1

        layout.addWidget(QLabel("Голос TTS:"), row, 0)
        layout.addWidget(self.input_tts_voice, row, 1)
        row += 1

        buttons = QHBoxLayout()
        self.btn_save_settings = QPushButton("Сохранить настройки")
        self.btn_apply_ads = QPushButton("Применить ON/OFF рекламы")
        self.btn_save_settings.setMinimumHeight(38)
        self.btn_apply_ads.setMinimumHeight(38)
        buttons.addWidget(self.btn_save_settings)
        buttons.addWidget(self.btn_apply_ads)

        layout.addLayout(buttons, row, 0, 1, 2)
        layout.setRowStretch(row + 1, 1)

        return box

    # -------------------------------------------------------------------------
    # helpers
    # -------------------------------------------------------------------------

    def _create_command_sender(self) -> Any:
        if CommandSender is None:
            return None

        for args, kwargs in (
            ((), {}),
            (("127.0.0.1", 8765), {}),
            ((), {"host": "127.0.0.1", "port": 8765}),
            (("http://127.0.0.1:8765",), {}),
            ((), {"base_url": "http://127.0.0.1:8765"}),
        ):
            try:
                return CommandSender(*args, **kwargs)
            except Exception:
                continue

        return None

    def _populate_tts_voices(self) -> None:
        self.input_tts_voice.clear()
        for label, value in self.TTS_VOICE_PRESETS:
            self.input_tts_voice.addItem(label, value)

    def _tts_value_from_display(self, display_text: str) -> str:
        text = (display_text or "").strip()
        if not text:
            return "default"

        for label, value in self.TTS_VOICE_PRESETS:
            if text == label or text == value:
                return value

        return text

    def _tts_display_from_value(self, voice_value: str) -> str:
        value = (voice_value or "").strip() or "default"

        for label, preset_value in self.TTS_VOICE_PRESETS:
            if value == preset_value:
                return label

        return value

    def _normalize_volume_text(self, raw_value: str, fallback: str) -> str:
        text = str(raw_value or "").strip().replace(",", ".")
        if not text:
            text = fallback

        try:
            value = float(text)
        except ValueError:
            value = float(fallback)

        if value < 0:
            value = 0.0
        elif value > 1:
            value = 1.0

        return f"{value:.2f}"

    def _apply_volume_formatting(self) -> None:
        self.input_music_volume.setText(
            self._normalize_volume_text(self.input_music_volume.text(), "0.35")
        )
        self.input_tts_volume.setText(
            self._normalize_volume_text(self.input_tts_volume.text(), "1.00")
        )

    def _set_notice(self, text: str, level: str = "info", timeout_ms: int = 4000) -> None:
        styles = {
            "info": (
                "background: rgba(59,130,246,0.12);"
                "border: 1px solid rgba(59,130,246,0.35);"
                "color: #dbeafe;"
            ),
            "success": (
                "background: rgba(34,197,94,0.12);"
                "border: 1px solid rgba(34,197,94,0.35);"
                "color: #dcfce7;"
            ),
            "warning": (
                "background: rgba(245,158,11,0.12);"
                "border: 1px solid rgba(245,158,11,0.35);"
                "color: #fef3c7;"
            ),
            "error": (
                "background: rgba(239,68,68,0.12);"
                "border: 1px solid rgba(239,68,68,0.35);"
                "color: #fee2e2;"
            ),
        }
        style = styles.get(level, styles["info"])
        self.notice_label.setStyleSheet(
            f"padding: 8px 12px; border-radius: 8px; font-size: 13px; {style}"
        )
        self.notice_label.setText(text)
        self.notice_label.show()

        self.notice_timer.stop()
        if timeout_ms > 0:
            self.notice_timer.start(timeout_ms)

    def _clear_notice(self) -> None:
        self.notice_label.clear()
        self.notice_label.hide()

    def _show_info(self, text: str) -> None:
        self._set_notice(text, "success")

    def _show_warning(self, text: str) -> None:
        self._set_notice(text, "warning", 5500)

    def _show_error(self, text: str, popup: bool = True) -> None:
        self._set_notice(text, "error", 7000)
        if popup:
            QMessageBox.critical(self, "Backend", text)

    def _status_style(self, state: str) -> str:
        colors = {
            "online": "#12a150",
            "offline": "#d32f2f",
            "starting": "#f39c12",
            "stopping": "#f39c12",
            "error": "#d32f2f",
        }
        color = colors.get(state, "#444444")
        return f"font-size: 28px; font-weight: 700; color: {color};"

    def _set_status(self, state: str, text: Optional[str] = None) -> None:
        self._current_state = state
        self.status_label.setStyleSheet(self._status_style(state))
        self.status_label.setText(text or f"Статус: {state}")

    def _provider_style(self, state: str) -> tuple[str, str]:
        mapping = {
            "online": ("● online", "#22c55e"),
            "starting": ("● starting", "#f59e0b"),
            "disabled": ("● disabled", "#94a3b8"),
            "error": ("● error", "#ef4444"),
            "offline": ("● offline", "#6b7280"),
        }
        return mapping.get(state, ("● unknown", "#6b7280"))

    def _set_provider_status(self, key: str, state: str) -> None:
        label = self.provider_status_labels.get(key)
        if label is None:
            return

        text, color = self._provider_style(state)
        label.setText(text)
        label.setStyleSheet(f"font-size: 13px; font-weight: 800; color: {color};")

    def _parse_provider_statuses_from_logs(self, logs_text: str) -> dict[str, str]:
        states = {key: "offline" for key, _ in self.PROVIDERS}
        lines = [line.strip().lower() for line in str(logs_text or "").splitlines() if line.strip()]

        for line in lines:
            if "provider twitch отключён" in line:
                states["twitch"] = "disabled"
            if "provider trovo отключён" in line:
                states["trovo"] = "disabled"

            if "запуск provider: twitch" in line:
                states["twitch"] = "starting"
            if "запуск provider: youtube" in line:
                states["youtube"] = "starting"
            if "запуск provider: trovo" in line:
                states["trovo"] = "starting"
            if "запуск provider: donation_alerts" in line:
                states["donation_alerts"] = "starting"
            if "запуск provider: vk_play" in line:
                states["vk_play"] = "starting"

            if "twitch provider: run() started" in line or "twitch: websocket connected" in line:
                states["twitch"] = "online"
            if "youtube provider: run() started" in line:
                states["youtube"] = "online"
            if "trovo provider: run() started" in line or "trovo: websocket connected" in line:
                states["trovo"] = "online"
            if (
                "donationalerts: websocket connected" in line
                or "donationalerts: подтверждена подписка" in line
                or "donationalerts: подключаем канал" in line
            ):
                states["donation_alerts"] = "online"
            if (
                "vk play: websocket connected" in line
                or "vk play: connect confirmed" in line
                or "vk play: subscribe confirmed" in line
            ):
                states["vk_play"] = "online"

            if "twitch provider error" in line or ("providers.twitch" in line and "error" in line):
                states["twitch"] = "error"
            if "youtube provider error" in line or ("providers.youtube" in line and "error" in line):
                states["youtube"] = "error"
            if "trovo provider error" in line or ("providers.trovo" in line and "error" in line):
                states["trovo"] = "error"
            if "donationalerts provider error" in line or ("providers.donation_alerts" in line and "error" in line):
                states["donation_alerts"] = "error"
            if "vk play provider error" in line or ("providers.vk_play" in line and "error" in line):
                states["vk_play"] = "error"

        return states

    def _update_provider_statuses(self, logs_text: str) -> None:
        if not self._is_online():
            for key, _ in self.PROVIDERS:
                self._set_provider_status(key, "offline")
            return

        states = self._parse_provider_statuses_from_logs(logs_text)
        for key, _ in self.PROVIDERS:
            self._set_provider_status(key, states.get(key, "offline"))

    def _is_online(self) -> bool:
        try:
            return bool(self.backend.is_running())
        except Exception:
            return False

    def _update_buttons_state(self) -> None:
        online = self._is_online()

        self.btn_start.setEnabled(not online)
        self.btn_stop.setEnabled(online)
        self.btn_restart.setEnabled(online)

        self.btn_overlay.setEnabled(online)
        self.btn_control.setEnabled(online)

        self.btn_send_test_alert.setEnabled(online)
        self.btn_apply_ads.setEnabled(True)
        self.btn_save_settings.setEnabled(True)

    def _load_settings_dict(self) -> dict[str, Any]:
        return self.config_manager.load()

    def _save_settings_dict(self, data: dict[str, Any]) -> None:
        self.config_manager.save(data)

    def _fetch_backend_settings(self) -> dict[str, Any] | None:
        try:
            if self.command_sender is None:
                return None

            response = self.command_sender.settings()
            if isinstance(response, dict):
                settings = response.get("settings")
                if isinstance(settings, dict):
                    return settings
            return None
        except Exception:
            return None

    def _apply_settings_to_form(self, data: dict[str, Any]) -> None:
        self.chk_show_ads.setChecked(bool(data.get("show_site_ads", False)))
        self.input_ad_title.setText(str(data.get("ad_title", "")))
        self.input_ad_line2.setText(str(data.get("ad_line2", "")))
        self.input_ad_line3.setText(str(data.get("ad_line3", "")))
        self.input_music_volume.setText(
            self._normalize_volume_text(str(data.get("music_volume", "0.35")), "0.35")
        )
        self.input_tts_volume.setText(
            self._normalize_volume_text(str(data.get("tts_volume", "1.00")), "1.00")
        )
        self._set_tts_voice_value(str(data.get("tts_voice", "default")))

    def _try_sync_settings_from_backend(self, show_notice: bool = False) -> bool:
        settings = self._fetch_backend_settings()
        if not settings:
            return False

        self._apply_settings_to_form(settings)
        self._synced_from_backend = True

        if show_notice:
            self._set_notice("Настройки подтянуты из backend.", "info", 3500)

        return True

    def _set_tts_voice_value(self, value: str) -> None:
        voice_value = (value or "").strip() or "default"
        display_text = self._tts_display_from_value(voice_value)

        existing_labels = [self.input_tts_voice.itemText(i) for i in range(self.input_tts_voice.count())]
        if display_text not in existing_labels:
            self.input_tts_voice.addItem(display_text, voice_value)

        self.input_tts_voice.setCurrentText(display_text)

    def _collect_form_settings(self) -> dict[str, Any]:
        self._apply_volume_formatting()
        return {
            "show_site_ads": self.chk_show_ads.isChecked(),
            "ad_title": self.input_ad_title.text().strip(),
            "ad_line2": self.input_ad_line2.text().strip(),
            "ad_line3": self.input_ad_line3.text().strip(),
            "music_volume": self.input_music_volume.text().strip(),
            "tts_volume": self.input_tts_volume.text().strip(),
            "tts_voice": self._tts_value_from_display(self.input_tts_voice.currentText()),
        }

    def _collect_backend_settings_payload(self) -> dict[str, Any]:
        gui = self._collect_form_settings()
        return {
            "show_site_ads": gui["show_site_ads"],
            "ad_title": gui["ad_title"],
            "ad_line2": gui["ad_line2"],
            "ad_line3": gui["ad_line3"],
            "music_volume": gui["music_volume"],
            "tts_volume": gui["tts_volume"],
            "tts_voice": gui["tts_voice"],
        }

    def _load_settings_into_form(self) -> None:
        data = self._load_settings_dict()
        self._apply_settings_to_form(data)

    def _set_logs_text(self, text: str) -> None:
        text = text or ""
        if text == self._last_logs_text:
            return

        self.logs_box.setPlainText(text)
        self._last_logs_text = text

        cursor = self.logs_box.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.logs_box.setTextCursor(cursor)

    def _safe_get_logs(self) -> str:
        try:
            if hasattr(self.backend, "get_logs"):
                return str(self.backend.get_logs())
            if hasattr(self.backend, "get_logs_text"):
                return str(self.backend.get_logs_text())
        except Exception as e:
            return f"[ui-error] Не удалось получить лог: {e}\n"
        return ""

    def _sender_call(self, method_names: list[str], **payload: Any) -> tuple[bool, str]:
        if self.command_sender is None:
            return False, "CommandSender недоступен."

        for method_name in method_names:
            method = getattr(self.command_sender, method_name, None)
            if method is None or not callable(method):
                continue

            try:
                sig = inspect.signature(method)
                if any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
                    result = method(**payload)
                else:
                    accepted = {
                        name: value
                        for name, value in payload.items()
                        if name in sig.parameters
                    }
                    result = method(**accepted)
            except Exception as e:
                return False, f"{method_name}: {e}"

            if isinstance(result, tuple) and len(result) == 2:
                return bool(result[0]), str(result[1])
            if isinstance(result, bool):
                return result, "OK" if result else "Команда не выполнена."
            if result is None:
                return True, "OK"
            return True, str(result)

        return False, "Подходящий метод в CommandSender не найден."

    def _http_post_json(self, path: str, payload: dict[str, Any]) -> tuple[bool, str]:
        import requests

        base_url = "http://127.0.0.1:8765"
        url = f"{base_url}{path}"

        try:
            session = requests.Session()
            session.trust_env = False

            resp = session.post(url, json=payload, timeout=5)

            if resp.ok:
                try:
                    return True, str(resp.json())
                except Exception:
                    return True, resp.text or f"HTTP {resp.status_code}"

            return False, resp.text or f"HTTPError {resp.status_code}"

        except Exception as e:
            return False, str(e)

    # -------------------------------------------------------------------------
    # actions
    # -------------------------------------------------------------------------

    def refresh_everything(self) -> None:
        online = self._is_online()
        logs_text = self._safe_get_logs()

        if online:
            self._set_status("online", "Статус: online")
            if not self._synced_from_backend:
                self._try_sync_settings_from_backend(show_notice=False)
        else:
            self._set_status("offline", "Статус: offline")
            self._synced_from_backend = False

        self._update_buttons_state()
        self._set_logs_text(logs_text)
        self._update_provider_statuses(logs_text)

    def on_start_backend(self) -> None:
        self._set_status("starting", "Статус: starting...")
        QApplication.processEvents()

        try:
            ok, msg = self.backend.start()
        except Exception as e:
            ok, msg = False, f"Ошибка запуска backend: {e}"

        self.refresh_everything()
        if ok:
            self._try_sync_settings_from_backend(show_notice=False)
            self._show_info(msg)
        else:
            self._set_status("error", "Статус: error")
            self._show_error(msg)

    def on_stop_backend(self) -> None:
        self._set_status("stopping", "Статус: stopping...")
        QApplication.processEvents()

        try:
            ok, msg = self.backend.stop()
        except Exception as e:
            ok, msg = False, f"Ошибка остановки backend: {e}"

        self.refresh_everything()
        if ok:
            self._show_info(msg)
        else:
            self._show_error(msg)

    def on_restart_backend(self) -> None:
        self._set_status("starting", "Статус: restarting...")
        QApplication.processEvents()

        try:
            ok, msg = self.backend.restart()
        except Exception as e:
            ok, msg = False, f"Ошибка перезапуска backend: {e}"

        self._synced_from_backend = False
        self.refresh_everything()
        if ok:
            self._try_sync_settings_from_backend(show_notice=False)
            self._show_info(msg)
        else:
            self._set_status("error", "Статус: error")
            self._show_error(msg)

    def on_open_overlay(self) -> None:
        if not self._is_online():
            self._show_warning("Backend сейчас offline.")
            return
        webbrowser.open(self.backend.get_overlay_url())
        self._set_notice("Открыт overlay в браузере.", "info")

    def on_open_control(self) -> None:
        if not self._is_online():
            self._show_warning("Backend сейчас offline.")
            return
        webbrowser.open(self.backend.get_control_url())
        self._set_notice("Открыт control в браузере.", "info")

    def on_send_test_alert(self) -> None:
        if not self._is_online():
            self._show_warning("Сначала запусти backend.")
            return

        donor = self.input_sender.text().strip() or "TarkoFF Supporter"
        amount = self.input_amount.text().strip() or "250"
        message = self.input_message.text().strip() or "Тест из GUI"

        payload = {
            "provider": "donation_alerts",
            "event_type": "donation",
            "title": "Новый донат",
            "donor": donor,
            "amount": amount,
            "message": message,
        }

        ok, msg = self._http_post_json("/api/test", payload)

        if ok:
            self._show_info("Тестовый донат отправлен.")
        else:
            self._show_error(f"Не удалось отправить тестовый донат.\n\n{msg}", popup=False)

        self.refresh_everything()

    def on_save_settings(self) -> None:
        data = self._collect_form_settings()

        try:
            self._save_settings_dict(data)
        except Exception as e:
            self._show_error(f"Не удалось сохранить settings.json:\n{e}")
            return

        self._show_info("Настройки сохранены в config/settings.json.")

    def on_apply_ads(self) -> None:
        gui_data = self._collect_form_settings()

        try:
            self._save_settings_dict(gui_data)
        except Exception as e:
            self._show_error(f"Не удалось сохранить settings.json:\n{e}")
            return

        if not self._is_online():
            self._set_notice("Настройки сохранены локально. Backend сейчас offline.", "info", 5000)
            return

        backend_payload = self._collect_backend_settings_payload()

        try:
            if self.command_sender is None:
                raise RuntimeError("CommandSender недоступен.")

            self.command_sender.update_settings(backend_payload)
            self.command_sender.toggle_ad(gui_data["show_site_ads"])
            self._synced_from_backend = False

            self._show_info("Настройки рекламы применены в backend.")
        except Exception as e:
            self._show_error(
                "Настройки сохранены локально, но не удалось применить их в backend.\n\n"
                f"{e}",
                popup=False,
            )

        self.refresh_everything()

    def on_copy_log(self) -> None:
        QApplication.clipboard().setText(self.logs_box.toPlainText())
        self._show_info("Лог скопирован в буфер обмена.")

    def on_clear_log(self) -> None:
        try:
            if hasattr(self.backend, "clear_logs"):
                self.backend.clear_logs()
        except Exception:
            pass

        self.logs_box.clear()
        self._last_logs_text = ""
        self._set_notice("Лог очищен.", "info")
        self._update_provider_statuses("")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        try:
            if hasattr(self, "refresh_timer") and self.refresh_timer is not None:
                self.refresh_timer.stop()
            if hasattr(self, "notice_timer") and self.notice_timer is not None:
                self.notice_timer.stop()
        except Exception:
            pass
        super().closeEvent(event)