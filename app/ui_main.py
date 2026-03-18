from __future__ import annotations

import time
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
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.backend_manager import BackendManager
from app.services.config_manager import ConfigManager


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

    OBS_SOURCE_DEFAULTS: dict[str, dict[str, Any]] = {
        "qr": {
            "title": "TarkoFFchanin QR Donate Premium v2",
            "scene": "2",
            "source": "TarkoFFchanin QR Donate Premium v2",
            "duration": "15",
            "interval": "300",
            "enabled": True,
            "auto": False,
            "favorite": True,
        },
        "social": {
            "title": "TarkoFFchanin Social Promo Premium",
            "scene": "3",
            "source": "TarkoFFchanin Social Promo Premium",
            "duration": "10",
            "interval": "300",
            "enabled": True,
            "auto": False,
            "favorite": True,
        },
        "brb": {
            "title": "TarkoFFchanin Be Right Back Clean",
            "scene": "3",
            "source": "TarkoFFchanin Be Right Back Clean",
            "duration": "10",
            "interval": "300",
            "enabled": True,
            "auto": False,
            "favorite": False,
        },
        "soon": {
            "title": "TarkoFFchanin Stream Soon Timer 10m",
            "scene": "1",
            "source": "TarkoFFchanin Stream Soon Timer 10m",
            "duration": "10",
            "interval": "300",
            "enabled": True,
            "auto": False,
            "favorite": False,
        },
        "chat": {
            "title": "TarkoFFchanin Chat Layout Clean Working 16x9",
            "scene": "Сцена 2",
            "source": "TarkoFFchanin Chat Layout Clean Working 16x9",
            "duration": "10",
            "interval": "300",
            "enabled": True,
            "auto": False,
            "favorite": False,
        },
    }

    OBS_SOURCE_LAYOUT: list[tuple[str, int, int, int, int]] = [
        ("qr", 0, 0, 1, 1),
        ("social", 0, 1, 1, 1),
        ("brb", 1, 0, 1, 1),
        ("soon", 1, 1, 1, 1),
        ("chat", 2, 0, 1, 2),
    ]

    def __init__(self) -> None:
        super().__init__()

        self.project_root = Path(__file__).resolve().parents[1]
        self.config_dir = self.project_root / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.config_dir / "settings.json"

        self.backend = BackendManager()
        self.config_manager = ConfigManager(self.settings_path)

        self._last_logs_text = ""
        self._current_state = "offline"
        self.provider_status_labels: dict[str, QLabel] = {}
        self.obs_last_run_at: dict[str, float] = {}
        self._auto_processing = False
        self.browser_source_names: list[str] = []

        self.module_group_boxes: dict[str, QGroupBox] = {}
        self.module_state_labels: dict[str, QLabel] = {}
        self.module_deactivate_timers: dict[str, QTimer] = {}
        self.module_visual_states: dict[str, str] = {}

        self.favorite_order: list[str] = list(self.OBS_SOURCE_DEFAULTS.keys())

        self._test_all_running = False
        self._test_queue: list[str] = []
        self._test_current_prefix: str | None = None
        self._test_timer = QTimer(self)
        self._test_timer.setSingleShot(True)
        self._test_timer.timeout.connect(self._run_next_module_test)

        self.setWindowTitle("TarkoFF Stream Center v0.1")
        self.resize(1360, 980)

        self.notice_timer = QTimer(self)
        self.notice_timer.setSingleShot(True)
        self.notice_timer.timeout.connect(self._clear_notice)

        self._build_ui()
        self._load_settings_into_form()
        self._refresh_all_module_visual_states()
        self._rebuild_favorites_group_contents()
        self._prime_auto_run_state()
        self.refresh_everything()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(1000)
        self.refresh_timer.timeout.connect(self.refresh_everything)
        self.refresh_timer.start()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        self.status_label = QLabel("Статус: offline")
        self.status_label.setStyleSheet(
            "font-size: 24px; font-weight: 700; color: #d32f2f;"
        )
        root.addWidget(self.status_label)

        top_buttons = QHBoxLayout()
        top_buttons.setSpacing(8)

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
            btn.setMinimumHeight(34)
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
        self.tab_obs = self._build_obs_tab()
        self.tab_settings = self._build_settings_tab()
        self.tab_logs = self._build_logs_tab()

        self.tabs.addTab(self.tab_alerts, "Алерты")
        self.tabs.addTab(self.tab_obs, "OBS")
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
        self.btn_obs_connect.clicked.connect(self.on_obs_connect_clicked)
        self.btn_obs_inventory.clicked.connect(self.on_obs_inventory_clicked)
        self.btn_browser_sources.clicked.connect(self.on_browser_sources_clicked)
        self.btn_refresh_all_browser.clicked.connect(self.on_refresh_all_browser_sources)
        self.btn_test_all_modules.clicked.connect(self.on_test_all_modules)
        self.btn_stop_test_all.clicked.connect(self.on_stop_test_all_modules)

        for prefix in self.OBS_SOURCE_DEFAULTS:
            getattr(self, f"btn_{prefix}_show").clicked.connect(
                lambda _=False, p=prefix: self._on_show_source(p)
            )
            getattr(self, f"btn_{prefix}_show_temp").clicked.connect(
                lambda _=False, p=prefix: self._on_show_source_temp(p)
            )
            getattr(self, f"btn_{prefix}_hide").clicked.connect(
                lambda _=False, p=prefix: self._on_hide_source(p)
            )
            getattr(self, f"btn_{prefix}_refresh_page").clicked.connect(
                lambda _=False, p=prefix: self._on_refresh_browser_source(p)
            )
            getattr(self, f"{prefix}_enabled_checkbox").stateChanged.connect(
                lambda _=0, p=prefix: self._on_module_checkbox_changed(p)
            )
            getattr(self, f"{prefix}_auto_checkbox").stateChanged.connect(
                lambda _=0, p=prefix: self._on_module_checkbox_changed(p)
            )
            getattr(self, f"{prefix}_favorite_checkbox").stateChanged.connect(
                lambda _=0, p=prefix: self._on_module_checkbox_changed(p)
            )

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
            "Быстрый сценарий проверки:\n\n"
            "1. Запусти backend\n"
            "2. Подключи OBS на вкладке OBS\n"
            "3. Открой overlay\n"
            "4. Отправь тестовый донат\n"
            "5. Проверь показ, refresh browser source и авто-модули"
        )
        layout.addWidget(self.info_box)

        layout.addStretch(1)
        return page

    def _build_obs_tab(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(10)

        outer.addWidget(self._build_obs_connection_group())
        outer.addWidget(self._build_browser_sources_group())
        outer.addWidget(self._build_obs_favorites_group())
        outer.addWidget(self._build_obs_action_log_group())

        tip = QLabel(
            "Названия сцен и источников должны совпадать с OBS один в один. "
            "Кнопка «Обновить стр.» работает только для Browser Source. "
            "Тест всех модулей запускает их по очереди."
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("font-size: 12px; color: #475569;")
        outer.addWidget(tip)

        grid_wrap = QWidget()
        grid = QGridLayout(grid_wrap)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        for prefix, row, col, row_span, col_span in self.OBS_SOURCE_LAYOUT:
            grid.addWidget(self._build_obs_source_group(prefix), row, col, row_span, col_span)

        outer.addWidget(grid_wrap)
        outer.addStretch(1)

        scroll.setWidget(content)
        page_layout.addWidget(scroll)
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
        self.btn_copy_log.setMinimumHeight(32)
        self.btn_clear_log.setMinimumHeight(32)

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
        layout.setVerticalSpacing(10)

        for idx, (key, title) in enumerate(self.PROVIDERS):
            name_label = QLabel(title)
            name_label.setStyleSheet("font-size: 13px; font-weight: 700; color: #111827;")

            status_label = QLabel("")
            status_label.setMinimumWidth(120)

            row = idx // 2
            col = (idx % 2) * 2

            layout.addWidget(name_label, row, col)
            layout.addWidget(status_label, row, col + 1)

            self.provider_status_labels[key] = status_label
            self._set_provider_status(key, "offline")

        return box

    def _build_obs_connection_group(self) -> QGroupBox:
        box = QGroupBox("Подключение OBS")
        layout = QGridLayout(box)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)

        self.obs_host_input = QLineEdit("127.0.0.1")
        self.obs_port_input = QLineEdit("4455")
        self.obs_password_input = QLineEdit("")
        self.obs_password_input.setEchoMode(QLineEdit.Password)

        int_regex = QRegularExpression(r"^\d+$")
        int_validator = QRegularExpressionValidator(int_regex, self)
        self.obs_port_input.setValidator(int_validator)

        self.obs_status_label = QLabel("OBS: не подключён")
        self.obs_status_label.setStyleSheet(
            "font-size: 12px; font-weight: 800; color: #94a3b8;"
        )

        self.btn_obs_connect = QPushButton("Подключить OBS")
        self.btn_obs_connect.setMinimumHeight(32)

        layout.addWidget(QLabel("Host:"), 0, 0)
        layout.addWidget(self.obs_host_input, 0, 1)
        layout.addWidget(QLabel("Port:"), 0, 2)
        layout.addWidget(self.obs_port_input, 0, 3)

        layout.addWidget(QLabel("Password:"), 1, 0)
        layout.addWidget(self.obs_password_input, 1, 1, 1, 3)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        tools.addWidget(self.btn_obs_connect)
        tools.addStretch()

        layout.addLayout(tools, 2, 0, 1, 4)
        layout.addWidget(self.obs_status_label, 3, 0, 1, 4)
        return box

    def _build_browser_sources_group(self) -> QGroupBox:
        box = QGroupBox("Browser Source")
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        tools = QHBoxLayout()
        self.btn_browser_sources = QPushButton("Получить список Browser Source")
        self.btn_refresh_all_browser = QPushButton("Применить ко всем browser source refresh")
        self.btn_obs_inventory = QPushButton("Получить сцены и источники из OBS")
        self.btn_test_all_modules = QPushButton("Тест всех модулей")
        self.btn_stop_test_all = QPushButton("Стоп тест")

        for btn in (
            self.btn_browser_sources,
            self.btn_refresh_all_browser,
            self.btn_obs_inventory,
            self.btn_test_all_modules,
            self.btn_stop_test_all,
        ):
            btn.setMinimumHeight(30)
            tools.addWidget(btn)
        tools.addStretch()

        self.browser_sources_box = QPlainTextEdit()
        self.browser_sources_box.setReadOnly(True)
        self.browser_sources_box.setMinimumHeight(150)
        self.browser_sources_box.setPlaceholderText(
            "Здесь будет отдельный список только Browser Source."
        )

        self.obs_inventory_box = QPlainTextEdit()
        self.obs_inventory_box.setReadOnly(True)
        self.obs_inventory_box.setMinimumHeight(150)
        self.obs_inventory_box.setPlaceholderText(
            "Здесь будет список сцен и источников из OBS."
        )

        layout.addLayout(tools)
        layout.addWidget(self.browser_sources_box)
        layout.addWidget(self.obs_inventory_box)
        return box

    def _build_obs_favorites_group(self) -> QGroupBox:
        box = QGroupBox("Избранные источники")
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        self.obs_favorites_container = QWidget()
        self.obs_favorites_layout = QGridLayout(self.obs_favorites_container)
        self.obs_favorites_layout.setContentsMargins(0, 0, 0, 0)
        self.obs_favorites_layout.setHorizontalSpacing(8)
        self.obs_favorites_layout.setVerticalSpacing(8)

        layout.addWidget(self.obs_favorites_container)
        return box

    def _build_obs_action_log_group(self) -> QGroupBox:
        box = QGroupBox("Мини-лог OBS")
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        self.obs_action_log_box = QPlainTextEdit()
        self.obs_action_log_box.setReadOnly(True)
        self.obs_action_log_box.setMinimumHeight(130)
        self.obs_action_log_box.setPlaceholderText(
            "Здесь будут последние действия по OBS: show / hide / refresh / test."
        )

        layout.addWidget(self.obs_action_log_box)
        return box

    def _build_obs_source_group(self, prefix: str) -> QGroupBox:
        defaults = self.OBS_SOURCE_DEFAULTS[prefix]

        box = QGroupBox(str(defaults["title"]))
        layout = QGridLayout(box)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(6)

        scene_input = QLineEdit(str(defaults["scene"]))
        source_input = QLineEdit(str(defaults["source"]))
        duration_input = QLineEdit(str(defaults["duration"]))
        interval_input = QLineEdit(str(defaults["interval"]))

        int_regex = QRegularExpression(r"^\d+$")
        int_validator = QRegularExpressionValidator(int_regex, self)
        duration_input.setValidator(int_validator)
        interval_input.setValidator(int_validator)

        enabled_checkbox = QCheckBox("Вкл")
        enabled_checkbox.setChecked(bool(defaults["enabled"]))

        auto_checkbox = QCheckBox("Авто")
        auto_checkbox.setChecked(bool(defaults["auto"]))

        favorite_checkbox = QCheckBox("Избр")
        favorite_checkbox.setChecked(bool(defaults["favorite"]))

        state_label = QLabel("HIDDEN")

        btn_show = QPushButton("Показать")
        btn_show_temp = QPushButton("На N сек")
        btn_hide = QPushButton("Скрыть")
        btn_refresh_page = QPushButton("Обновить стр.")

        for btn in (btn_show, btn_show_temp, btn_hide, btn_refresh_page):
            btn.setMinimumHeight(28)

        setattr(self, f"{prefix}_scene_input", scene_input)
        setattr(self, f"{prefix}_source_input", source_input)
        setattr(self, f"{prefix}_duration_input", duration_input)
        setattr(self, f"{prefix}_interval_input", interval_input)
        setattr(self, f"{prefix}_enabled_checkbox", enabled_checkbox)
        setattr(self, f"{prefix}_auto_checkbox", auto_checkbox)
        setattr(self, f"{prefix}_favorite_checkbox", favorite_checkbox)
        setattr(self, f"btn_{prefix}_show", btn_show)
        setattr(self, f"btn_{prefix}_show_temp", btn_show_temp)
        setattr(self, f"btn_{prefix}_hide", btn_hide)
        setattr(self, f"btn_{prefix}_refresh_page", btn_refresh_page)

        self.module_group_boxes[prefix] = box
        self.module_state_labels[prefix] = state_label

        checks = QHBoxLayout()
        checks.setSpacing(10)
        checks.addWidget(enabled_checkbox)
        checks.addWidget(auto_checkbox)
        checks.addWidget(favorite_checkbox)
        checks.addStretch()
        checks.addWidget(state_label)

        layout.addLayout(checks, 0, 0, 1, 4)

        layout.addWidget(QLabel("Сцена:"), 1, 0)
        layout.addWidget(scene_input, 1, 1)
        layout.addWidget(QLabel("Показ:"), 1, 2)
        layout.addWidget(duration_input, 1, 3)

        layout.addWidget(QLabel("Источник:"), 2, 0)
        layout.addWidget(source_input, 2, 1, 1, 3)

        layout.addWidget(QLabel("Интервал авто:"), 3, 0)
        layout.addWidget(interval_input, 3, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        buttons.addWidget(btn_show)
        buttons.addWidget(btn_show_temp)
        buttons.addWidget(btn_hide)
        buttons.addWidget(btn_refresh_page)
        buttons.addStretch()

        layout.addLayout(buttons, 4, 0, 1, 4)

        box.setMinimumHeight(175)
        return box

    def _build_test_group(self) -> QGroupBox:
        box = QGroupBox("Тестовый алерт")
        layout = QGridLayout(box)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(10)

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
        self.btn_send_test_alert.setMinimumHeight(34)
        layout.addWidget(self.btn_send_test_alert, 3, 0, 1, 2)

        layout.setRowStretch(4, 1)
        return box

    def _build_settings_group(self) -> QGroupBox:
        box = QGroupBox("Реклама сайта / настройки")
        layout = QGridLayout(box)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(10)

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
        self.btn_save_settings.setMinimumHeight(34)
        self.btn_apply_ads.setMinimumHeight(34)
        buttons.addWidget(self.btn_save_settings)
        buttons.addWidget(self.btn_apply_ads)

        layout.addLayout(buttons, row, 0, 1, 2)
        layout.setRowStretch(row + 1, 1)
        return box

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _append_obs_log(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        line = f"[{stamp}] {text}"
        existing = self.obs_action_log_box.toPlainText().strip()
        new_text = f"{existing}\n{line}".strip() if existing else line
        lines = new_text.splitlines()[-120:]
        self.obs_action_log_box.setPlainText("\n".join(lines))
        cursor = self.obs_action_log_box.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.obs_action_log_box.setTextCursor(cursor)

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

    def _set_tts_voice_value(self, value: str) -> None:
        voice_value = (value or "").strip() or "default"
        display_text = self._tts_display_from_value(voice_value)
        existing_labels = [self.input_tts_voice.itemText(i) for i in range(self.input_tts_voice.count())]
        if display_text not in existing_labels:
            self.input_tts_voice.addItem(display_text, voice_value)
        self.input_tts_voice.setCurrentText(display_text)

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

    def _parse_positive_int(self, value: str, fallback: int, minimum: int = 1) -> int:
        text = str(value or "").strip()
        try:
            parsed = int(text)
        except Exception:
            parsed = fallback
        if parsed < minimum:
            parsed = minimum
        return parsed

    def _set_notice(self, text: str, level: str = "info", timeout_ms: int = 4000) -> None:
        styles = {
            "info": (
                "background: #dbeafe;"
                "border: 1px solid #60a5fa;"
                "color: #0f172a;"
            ),
            "success": (
                "background: #dcfce7;"
                "border: 1px solid #4ade80;"
                "color: #052e16;"
            ),
            "warning": (
                "background: #fef3c7;"
                "border: 1px solid #f59e0b;"
                "color: #78350f;"
            ),
            "error": (
                "background: #fee2e2;"
                "border: 1px solid #ef4444;"
                "color: #7f1d1d;"
            ),
        }
        style = styles.get(level, styles["info"])
        self.notice_label.setStyleSheet(
            "padding: 10px 12px;"
            "border-radius: 8px;"
            "font-size: 13px;"
            "font-weight: 700;"
            + style
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
        return f"font-size: 24px; font-weight: 700; color: {color};"

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
        label.setStyleSheet(f"font-size: 12px; font-weight: 800; color: {color};")

    def _module_box_style(self, state: str) -> str:
        if state == "active":
            border = "#22c55e"
            bg = "#ecfdf5"
            title = "#15803d"
        elif state == "off":
            border = "#d1d5db"
            bg = "#f8fafc"
            title = "#64748b"
        else:
            border = "#cbd5e1"
            bg = "#ffffff"
            title = "#0f172a"
        return (
            "QGroupBox {"
            f"border: 2px solid {border};"
            "border-radius: 8px;"
            "margin-top: 10px;"
            "padding-top: 10px;"
            f"background: {bg};"
            "}"
            "QGroupBox::title {"
            "subcontrol-origin: margin;"
            "left: 8px;"
            "padding: 0 4px 0 4px;"
            f"color: {title};"
            "font-weight: 700;"
            "font-size: 12px;"
            "}"
        )

    def _module_state_label_style(self, state: str) -> tuple[str, str]:
        if state == "active":
            return "ACTIVE", (
                "background: #dcfce7;"
                "border: 1px solid #22c55e;"
                "color: #166534;"
                "padding: 2px 7px;"
                "border-radius: 7px;"
                "font-size: 11px;"
                "font-weight: 700;"
            )
        if state == "off":
            return "OFF", (
                "background: #f1f5f9;"
                "border: 1px solid #cbd5e1;"
                "color: #64748b;"
                "padding: 2px 7px;"
                "border-radius: 7px;"
                "font-size: 11px;"
                "font-weight: 700;"
            )
        return "HIDDEN", (
            "background: #f8fafc;"
            "border: 1px solid #cbd5e1;"
            "color: #475569;"
            "padding: 2px 7px;"
            "border-radius: 7px;"
            "font-size: 11px;"
            "font-weight: 700;"
        )

    def _set_module_visual_state(self, prefix: str, state: str) -> None:
        box = self.module_group_boxes.get(prefix)
        label = self.module_state_labels.get(prefix)
        if box is None or label is None:
            return
        self.module_visual_states[prefix] = state
        box.setStyleSheet(self._module_box_style(state))
        text, style = self._module_state_label_style(state)
        label.setText(text)
        label.setStyleSheet(style)

    def _refresh_all_module_visual_states(self) -> None:
        for prefix in self.OBS_SOURCE_DEFAULTS:
            if getattr(self, f"{prefix}_enabled_checkbox").isChecked():
                self._set_module_visual_state(prefix, "hidden")
            else:
                self._set_module_visual_state(prefix, "off")

    def _cancel_module_deactivate(self, prefix: str) -> None:
        timer = self.module_deactivate_timers.pop(prefix, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()

    def _schedule_module_deactivate(self, prefix: str, seconds: int) -> None:
        self._cancel_module_deactivate(prefix)
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda p=prefix: self._on_local_module_timeout(p))
        timer.start(max(1, int(seconds)) * 1000)
        self.module_deactivate_timers[prefix] = timer

    def _on_local_module_timeout(self, prefix: str) -> None:
        self.module_deactivate_timers.pop(prefix, None)
        if getattr(self, f"{prefix}_enabled_checkbox").isChecked():
            self._set_module_visual_state(prefix, "hidden")
        else:
            self._set_module_visual_state(prefix, "off")
        self._rebuild_favorites_group_contents()

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

    def _module_is_enabled(self, prefix: str) -> bool:
        return bool(getattr(self, f"{prefix}_enabled_checkbox").isChecked())

    def _update_module_controls_state(self, prefix: str) -> None:
        online = self._is_online()
        enabled = self._module_is_enabled(prefix)
        getattr(self, f"btn_{prefix}_show").setEnabled(online and enabled)
        getattr(self, f"btn_{prefix}_show_temp").setEnabled(online and enabled)
        getattr(self, f"btn_{prefix}_hide").setEnabled(online and enabled)
        getattr(self, f"btn_{prefix}_refresh_page").setEnabled(online and enabled)
        auto_checkbox = getattr(self, f"{prefix}_auto_checkbox")
        auto_checkbox.setEnabled(enabled)
        if not enabled and auto_checkbox.isChecked():
            auto_checkbox.setChecked(False)

    def _update_buttons_state(self) -> None:
        online = self._is_online()
        self.btn_start.setEnabled(not online)
        self.btn_stop.setEnabled(online)
        self.btn_restart.setEnabled(online)
        self.btn_overlay.setEnabled(online)
        self.btn_control.setEnabled(online)
        self.btn_refresh.setEnabled(True)
        self.btn_send_test_alert.setEnabled(online)
        self.btn_obs_connect.setEnabled(online)
        self.btn_obs_inventory.setEnabled(online)
        self.btn_browser_sources.setEnabled(online)
        self.btn_refresh_all_browser.setEnabled(online)
        self.btn_test_all_modules.setEnabled(online and not self._test_all_running)
        self.btn_stop_test_all.setEnabled(online and self._test_all_running)
        for prefix in self.OBS_SOURCE_DEFAULTS:
            self._update_module_controls_state(prefix)
        self.btn_apply_ads.setEnabled(True)
        self.btn_save_settings.setEnabled(True)

    def _load_settings_dict(self) -> dict[str, Any]:
        return self.config_manager.load()

    def _save_settings_dict(self, data: dict[str, Any]) -> None:
        self.config_manager.save(data)

    def _normalize_favorite_order(self, order_raw: Any) -> list[str]:
        valid = list(self.OBS_SOURCE_DEFAULTS.keys())
        if not isinstance(order_raw, list):
            return valid.copy()
        result: list[str] = []
        for item in order_raw:
            text = str(item).strip()
            if text in valid and text not in result:
                result.append(text)
        for item in valid:
            if item not in result:
                result.append(item)
        return result

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

        self.obs_host_input.setText(str(data.get("obs_host", "127.0.0.1")))
        self.obs_port_input.setText(str(data.get("obs_port", "4455")))
        self.obs_password_input.setText(str(data.get("obs_password", "")))

        for prefix, defaults in self.OBS_SOURCE_DEFAULTS.items():
            getattr(self, f"{prefix}_scene_input").setText(
                str(data.get(f"obs_{prefix}_scene", defaults["scene"]))
            )
            getattr(self, f"{prefix}_source_input").setText(
                str(data.get(f"obs_{prefix}_source", defaults["source"]))
            )
            getattr(self, f"{prefix}_duration_input").setText(
                str(data.get(f"obs_{prefix}_duration", defaults["duration"]))
            )
            getattr(self, f"{prefix}_interval_input").setText(
                str(data.get(f"obs_{prefix}_interval", defaults["interval"]))
            )
            getattr(self, f"{prefix}_enabled_checkbox").setChecked(
                bool(data.get(f"obs_{prefix}_enabled", defaults["enabled"]))
            )
            getattr(self, f"{prefix}_auto_checkbox").setChecked(
                bool(data.get(f"obs_{prefix}_auto", defaults["auto"]))
            )
            getattr(self, f"{prefix}_favorite_checkbox").setChecked(
                bool(data.get(f"obs_{prefix}_favorite", defaults["favorite"]))
            )

        self.favorite_order = self._normalize_favorite_order(data.get("obs_favorites_order"))

    def _collect_form_settings(self) -> dict[str, Any]:
        self._apply_volume_formatting()
        data: dict[str, Any] = {
            "show_site_ads": self.chk_show_ads.isChecked(),
            "ad_title": self.input_ad_title.text().strip(),
            "ad_line2": self.input_ad_line2.text().strip(),
            "ad_line3": self.input_ad_line3.text().strip(),
            "music_volume": self.input_music_volume.text().strip(),
            "tts_volume": self.input_tts_volume.text().strip(),
            "tts_voice": self._tts_value_from_display(self.input_tts_voice.currentText()),
            "obs_host": self.obs_host_input.text().strip() or "127.0.0.1",
            "obs_port": self.obs_port_input.text().strip() or "4455",
            "obs_password": self.obs_password_input.text(),
            "obs_favorites_order": self.favorite_order.copy(),
        }
        for prefix, defaults in self.OBS_SOURCE_DEFAULTS.items():
            data[f"obs_{prefix}_scene"] = getattr(self, f"{prefix}_scene_input").text().strip() or str(defaults["scene"])
            data[f"obs_{prefix}_source"] = getattr(self, f"{prefix}_source_input").text().strip() or str(defaults["source"])
            data[f"obs_{prefix}_duration"] = getattr(self, f"{prefix}_duration_input").text().strip() or str(defaults["duration"])
            data[f"obs_{prefix}_interval"] = getattr(self, f"{prefix}_interval_input").text().strip() or str(defaults["interval"])
            data[f"obs_{prefix}_enabled"] = getattr(self, f"{prefix}_enabled_checkbox").isChecked()
            data[f"obs_{prefix}_auto"] = getattr(self, f"{prefix}_auto_checkbox").isChecked()
            data[f"obs_{prefix}_favorite"] = getattr(self, f"{prefix}_favorite_checkbox").isChecked()
        return data

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

    def _obs_values(self, prefix: str) -> dict[str, Any]:
        defaults = self.OBS_SOURCE_DEFAULTS[prefix]
        return {
            "scene_name": getattr(self, f"{prefix}_scene_input").text().strip() or str(defaults["scene"]),
            "source_name": getattr(self, f"{prefix}_source_input").text().strip() or str(defaults["source"]),
            "duration_sec": self._parse_positive_int(
                getattr(self, f"{prefix}_duration_input").text(),
                int(defaults["duration"]),
                minimum=1,
            ),
            "interval_sec": self._parse_positive_int(
                getattr(self, f"{prefix}_interval_input").text(),
                int(defaults["interval"]),
                minimum=5,
            ),
            "enabled": getattr(self, f"{prefix}_enabled_checkbox").isChecked(),
            "auto": getattr(self, f"{prefix}_auto_checkbox").isChecked(),
            "favorite": getattr(self, f"{prefix}_favorite_checkbox").isChecked(),
            "title": str(defaults["title"]),
        }

    def _favorite_enabled_prefixes(self) -> list[str]:
        ordered = self._normalize_favorite_order(self.favorite_order)
        return [p for p in ordered if getattr(self, f"{p}_favorite_checkbox").isChecked()]

    def _move_favorite(self, prefix: str, direction: int) -> None:
        ordered = self._normalize_favorite_order(self.favorite_order)
        if prefix not in ordered:
            return
        idx = ordered.index(prefix)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(ordered):
            return
        ordered[idx], ordered[new_idx] = ordered[new_idx], ordered[idx]
        self.favorite_order = ordered
        self._rebuild_favorites_group_contents()
        try:
            self._save_settings_dict(self._collect_form_settings())
        except Exception:
            pass
        self._append_obs_log(f"Изменён порядок избранных: {self.OBS_SOURCE_DEFAULTS[prefix]['title']}")

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

    def _http_post_json(self, path: str, payload: dict[str, Any]) -> tuple[bool, str]:
        import requests
        url = f"http://127.0.0.1:8765{path}"
        try:
            session = requests.Session()
            session.trust_env = False
            resp = session.post(url, json=payload, timeout=8)
            if resp.ok:
                try:
                    return True, str(resp.json())
                except Exception:
                    return True, resp.text or f"HTTP {resp.status_code}"
            return False, resp.text or f"HTTPError {resp.status_code}"
        except Exception as e:
            return False, str(e)

    def _http_post_json_data(self, path: str, payload: dict[str, Any]) -> tuple[bool, Any]:
        import requests
        url = f"http://127.0.0.1:8765{path}"
        try:
            session = requests.Session()
            session.trust_env = False
            resp = session.post(url, json=payload, timeout=8)
            if not resp.ok:
                try:
                    return False, resp.json()
                except Exception:
                    return False, resp.text or f"HTTPError {resp.status_code}"
            try:
                return True, resp.json()
            except Exception:
                return True, resp.text or f"HTTP {resp.status_code}"
        except Exception as e:
            return False, str(e)

    def _http_get_json_data(self, path: str) -> tuple[bool, Any]:
        import requests
        url = f"http://127.0.0.1:8765{path}"
        try:
            session = requests.Session()
            session.trust_env = False
            resp = session.get(url, timeout=5)
            if not resp.ok:
                try:
                    return False, resp.json()
                except Exception:
                    return False, resp.text or f"HTTPError {resp.status_code}"
            try:
                return True, resp.json()
            except Exception:
                return True, resp.text or f"HTTP {resp.status_code}"
        except Exception as e:
            return False, str(e)

    def _update_obs_status_label(self, connected: bool, text: str = "") -> None:
        if connected:
            self.obs_status_label.setText(text or "OBS: подключён")
            self.obs_status_label.setStyleSheet(
                "font-size: 12px; font-weight: 800; color: #22c55e;"
            )
        else:
            self.obs_status_label.setText(text or "OBS: не подключён")
            self.obs_status_label.setStyleSheet(
                "font-size: 12px; font-weight: 800; color: #94a3b8;"
            )

    def _refresh_obs_status(self) -> None:
        if not self._is_online():
            self._update_obs_status_label(False, "OBS: backend offline")
            return
        ok, data = self._http_get_json_data("/api/obs/status")
        if not ok or not isinstance(data, dict):
            self._update_obs_status_label(False, "OBS: статус недоступен")
            return
        connected = bool(data.get("connected", False))
        if connected:
            version = data.get("version", {}) or {}
            obs_ver = version.get("obs_version", "unknown")
            current_scene = data.get("current_scene", "")
            self._update_obs_status_label(True, f"OBS: подключён ({obs_ver}) | Сцена: {current_scene}")
        else:
            self._update_obs_status_label(False, "OBS: не подключён")

    def _format_obs_inventory(self, data: dict[str, Any]) -> str:
        current_scene = str(data.get("current_scene") or "").strip()
        scenes = data.get("scenes") or []
        sources_by_scene = data.get("sources_by_scene") or {}
        lines: list[str] = []
        if current_scene:
            lines.append(f"Текущая сцена: {current_scene}")
            lines.append("")
        for scene_name in scenes:
            lines.append(f"Сцена: {scene_name}")
            sources = sources_by_scene.get(scene_name) or []
            if sources:
                for source_name in sources:
                    lines.append(f"  - {source_name}")
            else:
                lines.append("  - (источники не найдены)")
            lines.append("")
        return "\n".join(lines).strip()

    def _format_browser_sources(self, data: dict[str, Any]) -> str:
        items = data.get("browser_sources") or []
        self.browser_source_names = [str(item.get("name", "")).strip() for item in items if str(item.get("name", "")).strip()]
        lines = ["Browser Source:", ""]
        if not items:
            lines.append("(ничего не найдено)")
            return "\n".join(lines)
        for item in items:
            name = str(item.get("name") or "").strip()
            kind = str(item.get("kind") or "").strip()
            lines.append(f"- {name} [{kind}]")
        return "\n".join(lines)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)

    def _rebuild_favorites_group_contents(self) -> None:
        self._clear_layout(self.obs_favorites_layout)
        favorite_prefixes = self._favorite_enabled_prefixes()
        if not favorite_prefixes:
            empty = QLabel("Нет избранных источников. Отметь галочкой «Избр» в нужном модуле.")
            empty.setWordWrap(True)
            empty.setStyleSheet("font-size: 12px; color: #64748b;")
            self.obs_favorites_layout.addWidget(empty, 0, 0)
            return

        row = 0
        for prefix in favorite_prefixes:
            title = QLabel(str(self.OBS_SOURCE_DEFAULTS[prefix]["title"]))
            title.setStyleSheet("font-size: 12px; font-weight: 700; color: #111827;")

            state = self.module_visual_states.get(prefix, "hidden")
            state_chip = QLabel("ACTIVE" if state == "active" else ("OFF" if state == "off" else "HIDDEN"))
            _, chip_style = self._module_state_label_style(state)
            state_chip.setStyleSheet(chip_style)

            btn_up = QPushButton("↑")
            btn_down = QPushButton("↓")
            btn_show = QPushButton("Показать")
            btn_show_temp = QPushButton("На N сек")
            btn_hide = QPushButton("Скрыть")
            btn_refresh_page = QPushButton("Обновить стр.")

            for btn in (btn_up, btn_down, btn_show, btn_show_temp, btn_hide, btn_refresh_page):
                btn.setMinimumHeight(26)

            btn_up.clicked.connect(lambda _=False, p=prefix: self._move_favorite(p, -1))
            btn_down.clicked.connect(lambda _=False, p=prefix: self._move_favorite(p, 1))
            btn_show.clicked.connect(lambda _=False, p=prefix: self._on_show_source(p))
            btn_show_temp.clicked.connect(lambda _=False, p=prefix: self._on_show_source_temp(p))
            btn_hide.clicked.connect(lambda _=False, p=prefix: self._on_hide_source(p))
            btn_refresh_page.clicked.connect(lambda _=False, p=prefix: self._on_refresh_browser_source(p))

            self.obs_favorites_layout.addWidget(title, row, 0)
            self.obs_favorites_layout.addWidget(state_chip, row, 1)
            self.obs_favorites_layout.addWidget(btn_up, row, 2)
            self.obs_favorites_layout.addWidget(btn_down, row, 3)
            self.obs_favorites_layout.addWidget(btn_show, row, 4)
            self.obs_favorites_layout.addWidget(btn_show_temp, row, 5)
            self.obs_favorites_layout.addWidget(btn_hide, row, 6)
            self.obs_favorites_layout.addWidget(btn_refresh_page, row, 7)
            row += 1

    def _prime_auto_run_state(self) -> None:
        now = time.monotonic()
        for prefix in self.OBS_SOURCE_DEFAULTS:
            if getattr(self, f"{prefix}_auto_checkbox").isChecked():
                self.obs_last_run_at[prefix] = now
            else:
                self.obs_last_run_at.pop(prefix, None)

    def _process_auto_modules(self) -> None:
        if self._auto_processing or self._test_all_running:
            return
        if not self._is_online():
            return
        self._auto_processing = True
        try:
            now = time.monotonic()
            for prefix in self.OBS_SOURCE_DEFAULTS:
                values = self._obs_values(prefix)
                if not values["enabled"]:
                    self.obs_last_run_at.pop(prefix, None)
                    continue
                if not values["auto"]:
                    self.obs_last_run_at.pop(prefix, None)
                    continue
                last_at = self.obs_last_run_at.get(prefix)
                if last_at is None:
                    self.obs_last_run_at[prefix] = now
                    continue
                if now - last_at < int(values["interval_sec"]):
                    continue
                payload = {
                    "scene_name": values["scene_name"],
                    "source_name": values["source_name"],
                    "duration_sec": int(values["duration_sec"]),
                }
                ok, data = self._http_post_json_data("/api/obs/show-source-temp", payload)
                self.obs_last_run_at[prefix] = now
                if ok and isinstance(data, dict) and data.get("ok"):
                    self._set_module_visual_state(prefix, "active")
                    self._schedule_module_deactivate(prefix, int(values["duration_sec"]))
                    self._rebuild_favorites_group_contents()
                    self._append_obs_log(f"Авто-показ: {values['title']}")
        finally:
            self._auto_processing = False

    # ------------------------------------------------------------------
    # sequential module test
    # ------------------------------------------------------------------

    def _test_enabled_prefixes(self) -> list[str]:
        return [p for p in self.OBS_SOURCE_DEFAULTS if self._obs_values(p)["enabled"]]

    def on_test_all_modules(self) -> None:
        if not self._is_online():
            self._show_warning("Сначала запусти backend.")
            return
        enabled_modules = self._test_enabled_prefixes()
        if not enabled_modules:
            self._show_warning("Нет включённых модулей для теста.")
            return
        self._test_queue = enabled_modules.copy()
        self._test_all_running = True
        self._test_current_prefix = None
        self._append_obs_log("Запущен тест всех модулей по очереди.")
        self._show_info("Тест всех модулей запущен.")
        self._update_buttons_state()
        self._run_next_module_test()

    def on_stop_test_all_modules(self) -> None:
        if not self._test_all_running:
            return
        self._test_timer.stop()
        self._test_all_running = False
        self._test_queue = []
        self._test_current_prefix = None
        self._append_obs_log("Тест всех модулей остановлен.")
        self._show_warning("Тест всех модулей остановлен.")
        self._update_buttons_state()

    def _run_next_module_test(self) -> None:
        if not self._test_all_running:
            return
        if not self._test_queue:
            self._test_all_running = False
            self._test_current_prefix = None
            self._append_obs_log("Тест всех модулей завершён.")
            self._show_info("Тест всех модулей завершён.")
            self._update_buttons_state()
            return

        prefix = self._test_queue.pop(0)
        self._test_current_prefix = prefix
        values = self._obs_values(prefix)
        payload = {
            "scene_name": values["scene_name"],
            "source_name": values["source_name"],
            "duration_sec": int(values["duration_sec"]),
        }
        ok, data = self._http_post_json_data("/api/obs/show-source-temp", payload)
        if ok and isinstance(data, dict) and data.get("ok"):
            self._set_module_visual_state(prefix, "active")
            self._schedule_module_deactivate(prefix, int(values["duration_sec"]))
            self._append_obs_log(f"Тест модуля: {values['title']}")
        else:
            message = data.get("message", f"Ошибка теста: {values['title']}") if isinstance(data, dict) else str(data)
            self._append_obs_log(f"Ошибка теста {values['title']}: {message}")
        self._rebuild_favorites_group_contents()
        self._test_timer.start((int(values["duration_sec"]) + 1) * 1000)

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------

    def refresh_everything(self) -> None:
        online = self._is_online()
        logs_text = self._safe_get_logs()
        if online:
            self._set_status("online", "Статус: online")
        else:
            self._set_status("offline", "Статус: offline")
        self._update_buttons_state()
        self._set_logs_text(logs_text)
        self._update_provider_statuses(logs_text)
        self._refresh_obs_status()
        self._process_auto_modules()

    def on_start_backend(self) -> None:
        self._set_status("starting", "Статус: starting...")
        QApplication.processEvents()
        try:
            ok, msg = self.backend.start()
        except Exception as e:
            ok, msg = False, f"Ошибка запуска backend: {e}"
        self.refresh_everything()
        if ok:
            self._show_info(msg)
            self._prime_auto_run_state()
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
        self.refresh_everything()
        if ok:
            self._show_info(msg)
            self._prime_auto_run_state()
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

    def on_obs_connect_clicked(self) -> None:
        if not self._is_online():
            self._show_warning("Сначала запусти backend.")
            return
        form_data = self._collect_form_settings()
        try:
            self._save_settings_dict(form_data)
        except Exception:
            pass
        password = str(form_data["obs_password"])
        if not password.strip():
            self._show_error("Введи пароль OBS в поле Password.", popup=False)
            self._update_obs_status_label(False, "OBS: пароль не указан")
            return
        payload = {
            "host": str(form_data["obs_host"]),
            "port": int(form_data["obs_port"]),
            "password": password,
        }
        ok, data = self._http_post_json_data("/api/obs/connect", payload)
        if ok and isinstance(data, dict) and data.get("ok"):
            version = data.get("version", {}) or {}
            obs_ver = version.get("obs_version", "unknown")
            self._update_obs_status_label(True, f"OBS: подключён ({obs_ver})")
            self._show_info(data.get("message", "OBS подключён"))
            self._append_obs_log("OBS подключён.")
            self._prime_auto_run_state()
        else:
            message = data.get("message", "Не удалось подключиться к OBS") if isinstance(data, dict) else str(data)
            self._update_obs_status_label(False, "OBS: ошибка подключения")
            self._show_error(message, popup=False)
            self._append_obs_log(f"Ошибка подключения OBS: {message}")
        self.refresh_everything()

    def on_obs_inventory_clicked(self) -> None:
        if not self._is_online():
            self._show_warning("Сначала запусти backend.")
            return
        ok, data = self._http_get_json_data("/api/obs/scenes-and-sources")
        if ok and isinstance(data, dict) and data.get("ok"):
            text = self._format_obs_inventory(data)
            self.obs_inventory_box.setPlainText(text)
            self._show_info("Список сцен и источников из OBS обновлён.")
            self._append_obs_log("Обновлён список сцен и источников OBS.")
        else:
            message = data.get("message", "Не удалось получить список сцен и источников") if isinstance(data, dict) else str(data)
            self._show_error(message, popup=False)
            self._append_obs_log(f"Ошибка чтения сцен OBS: {message}")

    def on_browser_sources_clicked(self) -> None:
        if not self._is_online():
            self._show_warning("Сначала запусти backend.")
            return
        ok, data = self._http_get_json_data("/api/obs/browser-sources")
        if ok and isinstance(data, dict) and data.get("ok"):
            text = self._format_browser_sources(data)
            self.browser_sources_box.setPlainText(text)
            self._show_info("Список Browser Source обновлён.")
            self._append_obs_log("Обновлён отдельный список Browser Source.")
        else:
            message = data.get("message", "Не удалось получить Browser Source") if isinstance(data, dict) else str(data)
            self._show_error(message, popup=False)
            self._append_obs_log(f"Ошибка чтения Browser Source: {message}")

    def on_refresh_all_browser_sources(self) -> None:
        if not self._is_online():
            self._show_warning("Сначала запусти backend.")
            return
        ok, data = self._http_post_json_data("/api/obs/refresh-all-browser-sources", {})
        if ok and isinstance(data, dict):
            results = data.get("results") or []
            count = int(data.get("count") or 0)
            errors = [item for item in results if item.get("status") != "ok"]
            if errors:
                self._show_warning(f"Refresh выполнен с ошибками. Успешно: {count - len(errors)}, ошибок: {len(errors)}")
            else:
                self._show_info(f"Refresh применён ко всем browser source: {count}")
            for item in results:
                name = str(item.get("name") or "").strip()
                message = str(item.get("message") or "").strip()
                self._append_obs_log(f"Refresh browser source: {name} — {message}")
        else:
            message = data.get("message", "Не удалось применить refresh ко всем browser source") if isinstance(data, dict) else str(data)
            self._show_error(message, popup=False)
            self._append_obs_log(f"Ошибка общего refresh browser source: {message}")

    def _on_module_checkbox_changed(self, prefix: str) -> None:
        enabled = getattr(self, f"{prefix}_enabled_checkbox").isChecked()
        auto = getattr(self, f"{prefix}_auto_checkbox").isChecked()
        if not enabled and auto:
            getattr(self, f"{prefix}_auto_checkbox").setChecked(False)
            auto = False
        if auto:
            self.obs_last_run_at[prefix] = time.monotonic()
        else:
            self.obs_last_run_at.pop(prefix, None)
        if enabled:
            if self.module_visual_states.get(prefix) == "off":
                self._set_module_visual_state(prefix, "hidden")
        else:
            self._cancel_module_deactivate(prefix)
            self._set_module_visual_state(prefix, "off")
        self._update_module_controls_state(prefix)
        self._rebuild_favorites_group_contents()
        try:
            self._save_settings_dict(self._collect_form_settings())
        except Exception:
            pass
        self._append_obs_log(f"Изменены галочки модуля: {self.OBS_SOURCE_DEFAULTS[prefix]['title']}")

    def _on_show_source(self, prefix: str) -> None:
        if not self._is_online():
            self._show_warning("Сначала запусти backend.")
            return
        values = self._obs_values(prefix)
        if not values["enabled"]:
            self._show_warning(f"Модуль выключен: {values['title']}")
            return
        self._save_settings_dict(self._collect_form_settings())
        self._cancel_module_deactivate(prefix)
        payload = {
            "scene_name": values["scene_name"],
            "source_name": values["source_name"],
        }
        ok, data = self._http_post_json_data("/api/obs/show-source", payload)
        if ok and isinstance(data, dict) and data.get("ok"):
            self._set_module_visual_state(prefix, "active")
            self._rebuild_favorites_group_contents()
            self._show_info(f"Показан источник: {values['title']}")
            self._append_obs_log(f"Показать: {values['title']}")
        else:
            message = data.get("message", f"Не удалось показать {values['title']}") if isinstance(data, dict) else str(data)
            self._show_error(message, popup=False)
            self._append_obs_log(f"Ошибка show {values['title']}: {message}")
        self.refresh_everything()

    def _on_show_source_temp(self, prefix: str) -> None:
        if not self._is_online():
            self._show_warning("Сначала запусти backend.")
            return
        values = self._obs_values(prefix)
        if not values["enabled"]:
            self._show_warning(f"Модуль выключен: {values['title']}")
            return
        self._save_settings_dict(self._collect_form_settings())
        payload = {
            "scene_name": values["scene_name"],
            "source_name": values["source_name"],
            "duration_sec": int(values["duration_sec"]),
        }
        ok, data = self._http_post_json_data("/api/obs/show-source-temp", payload)
        if ok and isinstance(data, dict) and data.get("ok"):
            self._set_module_visual_state(prefix, "active")
            self._schedule_module_deactivate(prefix, int(values["duration_sec"]))
            self._rebuild_favorites_group_contents()
            self._show_info(f"Показан на {values['duration_sec']} сек: {values['title']}")
            self._append_obs_log(f"Показать на {values['duration_sec']} сек: {values['title']}")
        else:
            message = data.get("message", f"Не удалось показать {values['title']}") if isinstance(data, dict) else str(data)
            self._show_error(message, popup=False)
            self._append_obs_log(f"Ошибка temp-show {values['title']}: {message}")
        self.refresh_everything()

    def _on_hide_source(self, prefix: str) -> None:
        if not self._is_online():
            self._show_warning("Сначала запусти backend.")
            return
        values = self._obs_values(prefix)
        if not values["enabled"]:
            self._show_warning(f"Модуль выключен: {values['title']}")
            return
        payload = {
            "scene_name": values["scene_name"],
            "source_name": values["source_name"],
        }
        ok, data = self._http_post_json_data("/api/obs/hide-source", payload)
        if ok and isinstance(data, dict) and data.get("ok"):
            self._cancel_module_deactivate(prefix)
            self._set_module_visual_state(prefix, "hidden")
            self._rebuild_favorites_group_contents()
            self._show_info(f"Скрыт источник: {values['title']}")
            self._append_obs_log(f"Скрыть: {values['title']}")
        else:
            message = data.get("message", f"Не удалось скрыть {values['title']}") if isinstance(data, dict) else str(data)
            self._show_error(message, popup=False)
            self._append_obs_log(f"Ошибка hide {values['title']}: {message}")
        self.refresh_everything()

    def _on_refresh_browser_source(self, prefix: str) -> None:
        if not self._is_online():
            self._show_warning("Сначала запусти backend.")
            return
        values = self._obs_values(prefix)
        if not values["enabled"]:
            self._show_warning(f"Модуль выключен: {values['title']}")
            return
        payload = {"source_name": values["source_name"]}
        ok, data = self._http_post_json_data("/api/obs/refresh-browser-source", payload)
        if ok and isinstance(data, dict) and data.get("ok"):
            self._show_info(f"Страница обновлена без кэша: {values['title']}")
            self._append_obs_log(f"Refresh browser source: {values['title']}")
        else:
            message = data.get("message", f"Не удалось обновить страницу: {values['title']}") if isinstance(data, dict) else str(data)
            self._show_error(message, popup=False)
            self._append_obs_log(f"Ошибка refresh {values['title']}: {message}")

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
        ok, msg = self._http_post_json("/api/settings", backend_payload)
        if not ok:
            self._show_error(f"Не удалось применить settings в backend:\n\n{msg}", popup=False)
            return
        ok, msg = self._http_post_json("/api/toggle-ad", {"enabled": gui_data["show_site_ads"]})
        if not ok:
            self._show_error(f"Не удалось применить ON/OFF рекламы:\n\n{msg}", popup=False)
            return
        self._show_info("Настройки рекламы применены в backend.")
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
        self.obs_action_log_box.clear()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        try:
            if hasattr(self, "refresh_timer") and self.refresh_timer is not None:
                self.refresh_timer.stop()
            if hasattr(self, "notice_timer") and self.notice_timer is not None:
                self.notice_timer.stop()
            self._test_timer.stop()
            for timer in list(self.module_deactivate_timers.values()):
                timer.stop()
                timer.deleteLater()
            self.module_deactivate_timers.clear()
        except Exception:
            pass
        super().closeEvent(event)
