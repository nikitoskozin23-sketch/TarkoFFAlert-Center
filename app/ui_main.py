from __future__ import annotations

import os
import webbrowser
import yaml
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QRegularExpression, QTimer, Qt
from PySide6.QtGui import QRegularExpressionValidator, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHeaderView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
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

        self.obs_inventory: dict[str, list[str]] = {}
        self.current_obs_scene: str = ""
        self._loading_scene = False
        self._updating_sources = False
        self.obs_connected = False
        self.source_items_by_name: dict[str, QListWidgetItem] = {}

        self.current_script_scene: str = ""
        self._loading_script_scene = False
        self._updating_scripts = False
        self.script_items_by_name: dict[str, QListWidgetItem] = {}

        self._updating_catalog = False
        self.catalog_row_items: list[QTreeWidgetItem] = []
        self._updating_script_library = False

        self.setWindowTitle("TarkoFF Stream Center")
        self.resize(1220, 940)

        self.notice_timer = QTimer(self)
        self.notice_timer.setSingleShot(True)
        self.notice_timer.timeout.connect(self._clear_notice)

        self._build_ui()
        self._apply_commercial_styles()
        self._load_settings_into_form()
        self._refresh_script_library_tree()
        self.refresh_everything()
        self._clear_notice()

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

        self.notice_card = QWidget()
        self.notice_card.setObjectName("noticeCard")
        self.notice_card.setMinimumHeight(58)
        self.notice_card_layout = QHBoxLayout(self.notice_card)
        self.notice_card_layout.setContentsMargins(14, 10, 14, 10)
        self.notice_card_layout.setSpacing(12)

        self.notice_icon_label = QLabel("●")
        self.notice_icon_label.setObjectName("noticeIcon")
        self.notice_icon_label.setAlignment(Qt.AlignCenter)
        self.notice_icon_label.setFixedSize(26, 26)

        self.notice_text_wrap = QWidget()
        self.notice_text_layout = QVBoxLayout(self.notice_text_wrap)
        self.notice_text_layout.setContentsMargins(0, 0, 0, 0)
        self.notice_text_layout.setSpacing(2)

        self.notice_title_label = QLabel("Состояние системы")
        self.notice_title_label.setObjectName("noticeTitle")
        self.notice_detail_label = QLabel("Backend остановлен.")
        self.notice_detail_label.setObjectName("noticeDetail")
        self.notice_detail_label.setWordWrap(True)

        self.notice_text_layout.addWidget(self.notice_title_label)
        self.notice_text_layout.addWidget(self.notice_detail_label)

        self.notice_badge_label = QLabel("OFFLINE")
        self.notice_badge_label.setObjectName("noticeBadge")
        self.notice_badge_label.setAlignment(Qt.AlignCenter)
        self.notice_badge_label.setMinimumWidth(108)

        self.notice_card_layout.addWidget(self.notice_icon_label, 0, Qt.AlignVCenter)
        self.notice_card_layout.addWidget(self.notice_text_wrap, 1)
        self.notice_card_layout.addWidget(self.notice_badge_label, 0, Qt.AlignVCenter)
        root.addWidget(self.notice_card)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        self.tab_alerts = self._build_alerts_tab()
        self.tab_obs = self._build_obs_tab()
        self.tab_scripts = self._build_scripts_tab()
        self.tab_catalog = self._build_catalog_tab()
        self.tab_settings = self._build_settings_tab()
        self.tab_logs = self._build_logs_tab()

        self.tabs.addTab(self.tab_alerts, "Алерты")
        self.tabs.addTab(self.tab_obs, "OBS / Источники")
        self.tabs.addTab(self.tab_scripts, "Скрипты")
        self.tabs.addTab(self.tab_catalog, "Каталог")
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
        self.btn_obs_reload_inventory.clicked.connect(self.on_obs_inventory_clicked)
        self.scene_list.currentTextChanged.connect(self.on_scene_changed)
        self.source_search_input.textChanged.connect(self.on_source_filter_changed)
        self.source_list.itemChanged.connect(self.on_source_item_changed)
        self.source_list.itemSelectionChanged.connect(self._refresh_source_status_labels)

        self.btn_scene_apply.clicked.connect(self.on_apply_scene_clicked)
        self.btn_scene_all_on.clicked.connect(self.on_scene_all_on_clicked)
        self.btn_scene_all_off.clicked.connect(self.on_scene_all_off_clicked)
        self.btn_scene_refresh_checked.clicked.connect(self.on_scene_refresh_checked_clicked)
        self.btn_scene_show_selected.clicked.connect(self.on_scene_show_selected_clicked)
        self.btn_scene_hide_selected.clicked.connect(self.on_scene_hide_selected_clicked)
        self.btn_move_selected_to_scripts.clicked.connect(self.on_move_selected_sources_to_scripts_clicked)

        self.script_scene_list.currentTextChanged.connect(self.on_script_scene_changed)
        self.script_search_input.textChanged.connect(self.on_script_filter_changed)
        self.script_list.itemChanged.connect(self.on_script_item_changed)
        self.script_list.itemSelectionChanged.connect(self._refresh_script_status_labels)
        self.btn_script_apply.clicked.connect(self.on_apply_script_scene_clicked)
        self.btn_script_all_on.clicked.connect(self.on_script_all_on_clicked)
        self.btn_script_all_off.clicked.connect(self.on_script_all_off_clicked)
        self.btn_script_refresh_checked.clicked.connect(self.on_script_refresh_checked_clicked)
        self.btn_script_show_selected.clicked.connect(self.on_script_show_selected_clicked)
        self.btn_script_hide_selected.clicked.connect(self.on_script_hide_selected_clicked)
        self.btn_move_selected_to_sources.clicked.connect(self.on_move_selected_scripts_to_sources_clicked)

        self.catalog_search_input.textChanged.connect(self.on_catalog_filters_changed)
        self.catalog_scene_filter.currentIndexChanged.connect(self.on_catalog_filters_changed)
        self.catalog_kind_filter.currentIndexChanged.connect(self.on_catalog_filters_changed)
        self.catalog_state_filter.currentIndexChanged.connect(self.on_catalog_filters_changed)
        self.catalog_tree.itemChanged.connect(self.on_catalog_item_changed)
        self.catalog_tree.itemSelectionChanged.connect(self._refresh_catalog_stats)
        self.btn_catalog_show_selected.clicked.connect(self.on_catalog_show_selected_clicked)
        self.btn_catalog_hide_selected.clicked.connect(self.on_catalog_hide_selected_clicked)
        self.btn_catalog_refresh_checked.clicked.connect(self.on_catalog_refresh_checked_clicked)
        self.btn_catalog_move_to_scripts.clicked.connect(self.on_catalog_move_selected_to_scripts_clicked)
        self.btn_catalog_move_to_sources.clicked.connect(self.on_catalog_move_selected_to_sources_clicked)
        self.btn_catalog_reload.clicked.connect(self._refresh_catalog_tree)

        self.btn_add_script_file.clicked.connect(self.on_add_script_file_clicked)
        self.btn_remove_script_file.clicked.connect(self.on_remove_script_file_clicked)
        self.btn_open_script_location.clicked.connect(self.on_open_script_location_clicked)
        self.btn_copy_script_path.clicked.connect(self.on_copy_script_path_clicked)
        self.script_library_tree.itemSelectionChanged.connect(self._update_script_library_buttons)

    def _build_alerts_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(12)

        layout.addWidget(self._build_providers_group())
        layout.addWidget(self._build_test_group())

        self.alerts_info_box = QTextEdit()
        self.alerts_info_box.setReadOnly(True)
        self.alerts_info_box.setFixedHeight(140)
        self.alerts_info_box.setPlainText(
            "Быстрая проверка:\n\n"
            "1. Запусти backend\n"
            "2. Подключи OBS\n"
            "3. Зайди на вкладку OBS\n"
            "4. Загрузи сцены и источники\n"
            "5. Отметь галочками, что должно быть включено на сцене\n"
            "6. Нажми «Применить для сцены»"
        )
        layout.addWidget(self.alerts_info_box)

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
        outer.addWidget(self._build_scene_manager_group())
        outer.addWidget(self._build_browser_sources_group())
        outer.addWidget(self._build_obs_actions_log_group())

        scroll.setWidget(content)
        page_layout.addWidget(scroll)
        return page

    def _build_scripts_tab(self) -> QWidget:
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

        outer.addWidget(self._build_script_manager_group())
        outer.addWidget(self._build_script_library_group())
        outer.addWidget(self._build_scripts_summary_group())
        outer.addStretch(1)

        scroll.setWidget(content)
        page_layout.addWidget(scroll)
        return page

    def _build_catalog_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)

        box = QGroupBox("Единый каталог элементов OBS")
        box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        box_layout = QVBoxLayout(box)
        box_layout.setSpacing(10)
        box_layout.setContentsMargins(12, 12, 12, 12)

        hint = QLabel(
            "Полноценная таблица: Сцена → Элемент → Категория → Тип → Включить/выключить. "
            "Галочка в последнем столбце сразу показывает или скрывает элемент в OBS."
        )
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 12px; color: #94a3b8;")
        box_layout.addWidget(hint)

        filters = QHBoxLayout()
        filters.setSpacing(8)

        self.catalog_search_input = QLineEdit()
        self.catalog_search_input.setPlaceholderText("Поиск по сцене или названию…")
        self.catalog_search_input.setClearButtonEnabled(True)
        self.catalog_search_input.setMinimumWidth(260)
        self.catalog_search_input.setMaximumWidth(340)

        self.catalog_scene_filter = QComboBox()
        self.catalog_scene_filter.setMinimumWidth(170)
        self.catalog_kind_filter = QComboBox()
        self.catalog_kind_filter.addItems(["Все элементы", "Только источники", "Только скрипты"])
        self.catalog_kind_filter.setMinimumWidth(170)
        self.catalog_state_filter = QComboBox()
        self.catalog_state_filter.addItems(["Все состояния", "Только включённые", "Только выключенные"])
        self.catalog_state_filter.setMinimumWidth(170)

        self.btn_catalog_reload = QPushButton("Обновить")
        self.btn_catalog_reload.setMinimumHeight(30)
        self.btn_catalog_reload.setMinimumWidth(120)
        self.btn_catalog_reload.setMaximumWidth(140)

        filters.addStretch(1)
        filters.addWidget(self.catalog_search_input)
        filters.addWidget(self.catalog_scene_filter)
        filters.addWidget(self.catalog_kind_filter)
        filters.addWidget(self.catalog_state_filter)
        filters.addWidget(self.btn_catalog_reload)
        filters.addStretch(1)
        box_layout.addLayout(filters)

        tools = QHBoxLayout()
        tools.setSpacing(6)
        self.btn_catalog_show_selected = QPushButton("Показать")
        self.btn_catalog_hide_selected = QPushButton("Скрыть")
        self.btn_catalog_refresh_checked = QPushButton("Обновить")
        self.btn_catalog_move_to_scripts = QPushButton("В скрипты")
        self.btn_catalog_move_to_sources = QPushButton("В источники")
        for btn in (
            self.btn_catalog_show_selected,
            self.btn_catalog_hide_selected,
            self.btn_catalog_refresh_checked,
            self.btn_catalog_move_to_scripts,
            self.btn_catalog_move_to_sources,
        ):
            btn.setMinimumHeight(30)
            btn.setMinimumWidth(118)
            btn.setMaximumWidth(150)
            tools.addWidget(btn)
        tools.addStretch(1)
        box_layout.addLayout(tools)

        self.catalog_stats_label = QLabel("Строк: 0 / отмечено: 0 / выделено: 0")
        self.catalog_stats_label.setAlignment(Qt.AlignCenter)
        self.catalog_stats_label.setStyleSheet("font-size: 12px; color: #94a3b8;")
        box_layout.addWidget(self.catalog_stats_label)

        self.catalog_tree = QTreeWidget()
        self.catalog_tree.setColumnCount(5)
        self.catalog_tree.setHeaderLabels(["Сцена", "Элемент", "Категория", "Тип", "Вкл/выкл"])
        self.catalog_tree.setAlternatingRowColors(True)
        self.catalog_tree.setRootIsDecorated(False)
        self.catalog_tree.setUniformRowHeights(True)
        self.catalog_tree.setAllColumnsShowFocus(True)
        self.catalog_tree.setItemsExpandable(False)
        self.catalog_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.catalog_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.catalog_tree.setMinimumHeight(600)
        self.catalog_tree.setMinimumWidth(1160)
        self.catalog_tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.catalog_tree.setSortingEnabled(True)
        self.catalog_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.catalog_tree.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.catalog_tree.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)

        header = self.catalog_tree.header()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(90)
        header.setDefaultAlignment(Qt.AlignCenter)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.catalog_tree.setColumnWidth(0, 220)
        self.catalog_tree.setColumnWidth(2, 170)
        self.catalog_tree.setColumnWidth(3, 180)
        self.catalog_tree.setColumnWidth(4, 120)

        box_layout.addWidget(self.catalog_tree)
        layout.addWidget(box, alignment=Qt.AlignHCenter)
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
        box.setStyleSheet(
            "QGroupBox { font-size: 13px; font-weight: 700; color: #e5e7eb; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; }"
        )
        layout = QGridLayout(box)
        layout.setHorizontalSpacing(24)
        layout.setVerticalSpacing(12)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 1)
        layout.setColumnStretch(3, 1)

        for idx, (key, title) in enumerate(self.PROVIDERS):
            name_label = QLabel(title)
            name_label.setMinimumWidth(140)
            name_label.setStyleSheet("font-size: 13px; font-weight: 700; color: #e5e7eb;")

            status_label = QLabel("")
            status_label.setMinimumWidth(120)

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
        layout.setVerticalSpacing(10)

        self.input_sender = QLineEdit("TarkoFF Supporter")
        self.input_amount = QLineEdit("250")
        self.input_message = QLineEdit("Тест из GUI")

        layout.addWidget(QLabel("От кого:"), 0, 0)
        layout.addWidget(self.input_sender, 0, 1)

        layout.addWidget(QLabel("Сумма:"), 1, 0)
        layout.addWidget(self.input_amount, 1, 1)

        layout.addWidget(QLabel("Сообщение:"), 2, 0)
        layout.addWidget(self.input_message, 2, 1)

        self.btn_send_test_alert = QPushButton("Отправить тестовый донат")
        self.btn_send_test_alert.setMinimumHeight(34)
        layout.addWidget(self.btn_send_test_alert, 3, 0, 1, 2)
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
        self.btn_obs_reload_inventory = QPushButton("Загрузить сцены и источники")
        self.btn_obs_connect.setMinimumHeight(32)
        self.btn_obs_reload_inventory.setMinimumHeight(32)

        layout.addWidget(QLabel("Host:"), 0, 0)
        layout.addWidget(self.obs_host_input, 0, 1)
        layout.addWidget(QLabel("Port:"), 0, 2)
        layout.addWidget(self.obs_port_input, 0, 3)

        layout.addWidget(QLabel("Password:"), 1, 0)
        layout.addWidget(self.obs_password_input, 1, 1, 1, 3)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        tools.addWidget(self.btn_obs_connect)
        tools.addWidget(self.btn_obs_reload_inventory)
        tools.addStretch()

        layout.addLayout(tools, 2, 0, 1, 4)
        layout.addWidget(self.obs_status_label, 3, 0, 1, 4)
        return box

    def _build_scene_manager_group(self) -> QGroupBox:
        box = QGroupBox("Сцены и источники")
        layout = QVBoxLayout(box)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.btn_scene_apply = QPushButton("Синхронизировать всё")
        self.btn_scene_all_on = QPushButton("Включить всё")
        self.btn_scene_all_off = QPushButton("Выключить всё")
        self.btn_scene_show_selected = QPushButton("Показать выбранные")
        self.btn_scene_hide_selected = QPushButton("Скрыть выбранные")
        self.btn_scene_refresh_checked = QPushButton("Обновить страницы у отмеченных")
        self.btn_move_selected_to_scripts = QPushButton("Перенести выбранные в «Скрипты»")

        for btn in (
            self.btn_scene_apply,
            self.btn_scene_all_on,
            self.btn_scene_all_off,
            self.btn_scene_show_selected,
            self.btn_scene_hide_selected,
            self.btn_scene_refresh_checked,
            self.btn_move_selected_to_scripts,
        ):
            btn.setMinimumHeight(32)
            top.addWidget(btn)

        top.addStretch()
        layout.addLayout(top)

        hint = QLabel(
            "Здесь только обычные источники. Скрипты вынесены в отдельную вкладку. "
            "Поставил галочку — источник сразу включился, снял — сразу скрылся."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 12px; color: #475569;")
        layout.addWidget(hint)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        scenes_panel = QWidget()
        scenes_layout = QVBoxLayout(scenes_panel)
        scenes_layout.setContentsMargins(0, 0, 0, 0)
        scenes_layout.setSpacing(8)

        scenes_title_row = QHBoxLayout()
        scenes_title = QLabel("Сцены")
        scenes_title.setStyleSheet("font-size: 13px; font-weight: 700;")
        self.scene_count_label = QLabel("0")
        self.scene_count_label.setStyleSheet("font-size: 12px; color: #64748b;")
        scenes_title_row.addWidget(scenes_title)
        scenes_title_row.addStretch()
        scenes_title_row.addWidget(self.scene_count_label)
        scenes_layout.addLayout(scenes_title_row)

        self.scene_list = QListWidget()
        self.scene_list.setAlternatingRowColors(True)
        self.scene_list.setMinimumWidth(200)
        self.scene_list.setMaximumWidth(210)
        self.scene_list.setMinimumHeight(300)
        scenes_layout.addWidget(self.scene_list)

        splitter.addWidget(scenes_panel)

        sources_panel = QWidget()
        sources_layout = QVBoxLayout(sources_panel)
        sources_layout.setContentsMargins(0, 0, 0, 0)
        sources_layout.setSpacing(8)

        source_header = QHBoxLayout()
        self.current_scene_label = QLabel("Источники сцены: —")
        self.current_scene_label.setAlignment(Qt.AlignCenter)
        self.current_scene_label.setStyleSheet("font-size: 13px; font-weight: 700;")
        self.source_stats_label = QLabel("0 / 0")
        self.source_stats_label.setStyleSheet("font-size: 12px; color: #64748b;")
        source_header.addWidget(self.current_scene_label)
        source_header.addStretch()
        source_header.addWidget(self.source_stats_label)
        sources_layout.addLayout(source_header)

        self.source_search_input = QLineEdit()
        self.source_search_input.setPlaceholderText("Поиск по источникам текущей сцены…")
        self.source_search_input.setClearButtonEnabled(True)
        self.source_search_input.setMaximumWidth(360)
        sources_layout.addWidget(self.source_search_input)

        self.source_list = QListWidget()
        self.source_list.setAlternatingRowColors(True)
        self.source_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.source_list.setMinimumHeight(300)
        self.source_list.setMinimumWidth(360)
        self.source_list.setMaximumWidth(430)
        self.source_list.setUniformItemSizes(True)
        sources_layout.addWidget(self.source_list)

        select_hint = QLabel(
            "Выделение в списке нужно для быстрых действий и для переноса элементов во вкладку «Скрипты»."
        )
        select_hint.setWordWrap(True)
        select_hint.setStyleSheet("font-size: 12px; color: #64748b;")
        sources_layout.addWidget(select_hint)

        sources_panel.setMaximumWidth(470)

        splitter.addWidget(sources_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([200, 410])
        splitter.setMaximumWidth(690)

        splitter_row = QHBoxLayout()
        splitter_row.addWidget(splitter)
        splitter_row.addStretch()
        layout.addLayout(splitter_row)
        return box

    def _build_script_manager_group(self) -> QGroupBox:
        box = QGroupBox("Сцены и скрипты")
        layout = QVBoxLayout(box)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.btn_script_apply = QPushButton("Синхронизировать всё")
        self.btn_script_all_on = QPushButton("Включить всё")
        self.btn_script_all_off = QPushButton("Выключить всё")
        self.btn_script_show_selected = QPushButton("Показать выбранные")
        self.btn_script_hide_selected = QPushButton("Скрыть выбранные")
        self.btn_script_refresh_checked = QPushButton("Обновить страницы у отмеченных")
        self.btn_move_selected_to_sources = QPushButton("Перенести выбранные в «Источники»")

        for btn in (
            self.btn_script_apply,
            self.btn_script_all_on,
            self.btn_script_all_off,
            self.btn_script_show_selected,
            self.btn_script_hide_selected,
            self.btn_script_refresh_checked,
            self.btn_move_selected_to_sources,
        ):
            btn.setMinimumHeight(32)
            top.addWidget(btn)

        top.addStretch()
        layout.addLayout(top)

        hint = QLabel(
            "Во вкладке «Скрипты» показываются OBS-элементы, которые GUI считает скриптами/оверлеями. "
            "Если что-то попало не туда — выдели элемент и перенеси его обратно в «Источники»."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 12px; color: #475569;")
        layout.addWidget(hint)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        scenes_panel = QWidget()
        scenes_layout = QVBoxLayout(scenes_panel)
        scenes_layout.setContentsMargins(0, 0, 0, 0)
        scenes_layout.setSpacing(8)

        scenes_title_row = QHBoxLayout()
        scenes_title = QLabel("Сцены")
        scenes_title.setStyleSheet("font-size: 13px; font-weight: 700;")
        self.script_scene_count_label = QLabel("0")
        self.script_scene_count_label.setStyleSheet("font-size: 12px; color: #64748b;")
        scenes_title_row.addWidget(scenes_title)
        scenes_title_row.addStretch()
        scenes_title_row.addWidget(self.script_scene_count_label)
        scenes_layout.addLayout(scenes_title_row)

        self.script_scene_list = QListWidget()
        self.script_scene_list.setAlternatingRowColors(True)
        self.script_scene_list.setMinimumWidth(200)
        self.script_scene_list.setMaximumWidth(210)
        self.script_scene_list.setMinimumHeight(300)
        scenes_layout.addWidget(self.script_scene_list)

        splitter.addWidget(scenes_panel)

        scripts_panel = QWidget()
        scripts_layout = QVBoxLayout(scripts_panel)
        scripts_layout.setContentsMargins(0, 0, 0, 0)
        scripts_layout.setSpacing(8)

        script_header = QHBoxLayout()
        self.current_script_scene_label = QLabel("Скрипты сцены: —")
        self.current_script_scene_label.setAlignment(Qt.AlignCenter)
        self.current_script_scene_label.setStyleSheet("font-size: 13px; font-weight: 700;")
        self.script_stats_label = QLabel("0 / 0")
        self.script_stats_label.setStyleSheet("font-size: 12px; color: #64748b;")
        script_header.addWidget(self.current_script_scene_label)
        script_header.addStretch()
        script_header.addWidget(self.script_stats_label)
        scripts_layout.addLayout(script_header)

        self.script_search_input = QLineEdit()
        self.script_search_input.setPlaceholderText("Поиск по скриптам текущей сцены…")
        self.script_search_input.setClearButtonEnabled(True)
        self.script_search_input.setMaximumWidth(360)
        scripts_layout.addWidget(self.script_search_input)

        self.script_list = QListWidget()
        self.script_list.setAlternatingRowColors(True)
        self.script_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.script_list.setMinimumHeight(300)
        self.script_list.setMinimumWidth(360)
        self.script_list.setMaximumWidth(430)
        self.script_list.setUniformItemSizes(True)
        scripts_layout.addWidget(self.script_list)

        scripts_hint = QLabel(
            "Скрипты тоже включаются и выключаются галочкой сразу, без отдельного применения."
        )
        scripts_hint.setWordWrap(True)
        scripts_hint.setStyleSheet("font-size: 12px; color: #64748b;")
        scripts_layout.addWidget(scripts_hint)

        scripts_panel.setMaximumWidth(470)

        splitter.addWidget(scripts_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([200, 410])
        splitter.setMaximumWidth(690)

        splitter_row = QHBoxLayout()
        splitter_row.addWidget(splitter)
        splitter_row.addStretch()
        layout.addLayout(splitter_row)
        return box

    def _build_script_library_group(self) -> QGroupBox:
        box = QGroupBox("Библиотека скриптов OBS")
        box.setMaximumWidth(980)
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        hint = QLabel(
            "Сюда можно добавлять файлы своих OBS-скриптов и оверлеев через кнопку, без правки кода программы. "
            "Важно: файлы .py/.lua регистрируются в библиотеке, но их автозагрузка в Tools → Scripts зависит не от этого GUI, а от самого OBS."
        )
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("font-size: 12px; color: #94a3b8;")
        layout.addWidget(hint)

        tools = QHBoxLayout()
        tools.addStretch()
        self.btn_add_script_file = QPushButton("Добавить файл")
        self.btn_open_script_location = QPushButton("Открыть папку")
        self.btn_copy_script_path = QPushButton("Копировать путь")
        self.btn_remove_script_file = QPushButton("Удалить из библиотеки")
        for btn in (
            self.btn_add_script_file,
            self.btn_open_script_location,
            self.btn_copy_script_path,
            self.btn_remove_script_file,
        ):
            btn.setMinimumHeight(28)
            btn.setMaximumWidth(170)
            tools.addWidget(btn)
        tools.addStretch()
        layout.addLayout(tools)

        self.script_library_tree = QTreeWidget()
        self.script_library_tree.setColumnCount(4)
        self.script_library_tree.setHeaderLabels(["Имя", "Тип", "Файл", "Статус"])
        self.script_library_tree.setRootIsDecorated(False)
        self.script_library_tree.setAlternatingRowColors(True)
        self.script_library_tree.setUniformRowHeights(True)
        self.script_library_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.script_library_tree.setMinimumHeight(170)
        self.script_library_tree.setMaximumWidth(940)
        self.script_library_tree.setSortingEnabled(True)
        self.script_library_tree.header().setSectionResizeMode(QHeaderView.Interactive)
        self.script_library_tree.header().resizeSection(0, 210)
        self.script_library_tree.header().resizeSection(1, 120)
        self.script_library_tree.header().resizeSection(2, 430)
        self.script_library_tree.header().resizeSection(3, 120)
        layout.addWidget(self.script_library_tree, alignment=Qt.AlignHCenter)

        self.script_library_hint = QLabel("Файлов в библиотеке: 0")
        self.script_library_hint.setAlignment(Qt.AlignCenter)
        self.script_library_hint.setStyleSheet("font-size: 12px; color: #94a3b8;")
        layout.addWidget(self.script_library_hint)
        return box

    def _build_scripts_summary_group(self) -> QGroupBox:
        box = QGroupBox("Список скриптов")
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        summary_hint = QLabel(
            "Ниже — краткая сводка по всем элементам, которые помечены как скрипты. "
            "Это помогает быстро понять, где у тебя обычный источник, а где логический скрипт/оверлей."
        )
        summary_hint.setWordWrap(True)
        summary_hint.setStyleSheet("font-size: 12px; color: #475569;")
        layout.addWidget(summary_hint)

        self.scripts_summary_box = QPlainTextEdit()
        self.scripts_summary_box.setReadOnly(True)
        self.scripts_summary_box.setMinimumHeight(180)
        self.scripts_summary_box.setMaximumWidth(790)
        layout.addWidget(self.scripts_summary_box)
        return box

    def _build_browser_sources_group(self) -> QGroupBox:
        box = QGroupBox("Сводка по текущей сцене / обновление страниц")
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        tools = QHBoxLayout()
        self.btn_refresh_all_browser_sources = QPushButton("Обновить все загруженные источники")
        self.btn_refresh_all_browser_sources.setMinimumHeight(30)
        self.btn_refresh_all_browser_sources.clicked.connect(self.on_refresh_all_browser_sources_clicked)
        tools.addWidget(self.btn_refresh_all_browser_sources)
        tools.addStretch()
        layout.addLayout(tools)

        self.browser_sources_box = QPlainTextEdit()
        self.browser_sources_box.setReadOnly(True)
        self.browser_sources_box.setMinimumHeight(120)
        layout.addWidget(self.browser_sources_box)
        return box

    def _build_obs_actions_log_group(self) -> QGroupBox:
        box = QGroupBox("Журнал OBS-действий")
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        self.obs_actions_log = QPlainTextEdit()
        self.obs_actions_log.setReadOnly(True)
        self.obs_actions_log.setMinimumHeight(180)
        layout.addWidget(self.obs_actions_log)
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
        return box

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
        value = max(0.0, min(1.0, value))
        return f"{value:.2f}"

    def _apply_volume_formatting(self) -> None:
        self.input_music_volume.setText(self._normalize_volume_text(self.input_music_volume.text(), "0.35"))
        self.input_tts_volume.setText(self._normalize_volume_text(self.input_tts_volume.text(), "1.00"))

    def _set_notice(self, text: str, level: str = "info", timeout_ms: int = 4000) -> None:
        palette = {
            "info": {
                "title": "Статус системы",
                "badge": "OFFLINE",
                "icon": "●",
                "card": "background:qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #11213d, stop:1 #0b1220); border:1px solid #2563eb; border-radius:14px;",
                "icon_style": "color:#60a5fa; font-size:18px; font-weight:900; background:#0b2545; border:1px solid #1d4ed8; border-radius:13px;",
                "title_style": "color:#eff6ff; font-size:14px; font-weight:800;",
                "detail_style": "color:#bfdbfe; font-size:12px; font-weight:600;",
                "badge_style": "background:#0b2545; color:#dbeafe; border:1px solid #1d4ed8; border-radius:11px; padding:6px 12px; font-size:11px; font-weight:900; letter-spacing:1px;",
            },
            "success": {
                "title": "Система активна",
                "badge": "ONLINE",
                "icon": "●",
                "card": "background:qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0b2a22, stop:1 #0b1220); border:1px solid #22c55e; border-radius:14px;",
                "icon_style": "color:#4ade80; font-size:18px; font-weight:900; background:#082f1f; border:1px solid #16a34a; border-radius:13px;",
                "title_style": "color:#f0fdf4; font-size:14px; font-weight:800;",
                "detail_style": "color:#bbf7d0; font-size:12px; font-weight:600;",
                "badge_style": "background:#082f1f; color:#dcfce7; border:1px solid #16a34a; border-radius:11px; padding:6px 12px; font-size:11px; font-weight:900; letter-spacing:1px;",
            },
            "warning": {
                "title": "Требуется внимание",
                "badge": "WARNING",
                "icon": "●",
                "card": "background:qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #39250a, stop:1 #0b1220); border:1px solid #f59e0b; border-radius:14px;",
                "icon_style": "color:#fbbf24; font-size:18px; font-weight:900; background:#3b2500; border:1px solid #d97706; border-radius:13px;",
                "title_style": "color:#fffbeb; font-size:14px; font-weight:800;",
                "detail_style": "color:#fde68a; font-size:12px; font-weight:600;",
                "badge_style": "background:#3b2500; color:#fef3c7; border:1px solid #d97706; border-radius:11px; padding:6px 12px; font-size:11px; font-weight:900; letter-spacing:1px;",
            },
            "error": {
                "title": "Обнаружена ошибка",
                "badge": "ERROR",
                "icon": "●",
                "card": "background:qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3a0f14, stop:1 #0b1220); border:1px solid #ef4444; border-radius:14px;",
                "icon_style": "color:#f87171; font-size:18px; font-weight:900; background:#450a0a; border:1px solid #dc2626; border-radius:13px;",
                "title_style": "color:#fef2f2; font-size:14px; font-weight:800;",
                "detail_style": "color:#fecaca; font-size:12px; font-weight:600;",
                "badge_style": "background:#450a0a; color:#fee2e2; border:1px solid #dc2626; border-radius:11px; padding:6px 12px; font-size:11px; font-weight:900; letter-spacing:1px;",
            },
        }
        style = palette.get(level, palette["info"])
        self.notice_card.setStyleSheet(style["card"])
        self.notice_icon_label.setStyleSheet(style["icon_style"])
        self.notice_title_label.setStyleSheet(style["title_style"])
        self.notice_detail_label.setStyleSheet(style["detail_style"])
        self.notice_badge_label.setStyleSheet(style["badge_style"])
        self.notice_icon_label.setText(style["icon"])
        self.notice_title_label.setText(style["title"])
        self.notice_detail_label.setText(text)
        self.notice_badge_label.setText(style["badge"])
        self.notice_timer.stop()
        if timeout_ms > 0:
            self.notice_timer.start(timeout_ms)

    def _clear_notice(self) -> None:
        online = self._is_online()
        if online:
            self._set_notice("Backend запущен и готов к работе.", "success", 0)
        else:
            self._set_notice("Backend остановлен.", "info", 0)

    def _show_info(self, text: str) -> None:
        self._set_notice(text, "success")

    def _show_warning(self, text: str) -> None:
        self._set_notice(text, "warning", 5500)

    def _show_error(self, text: str, popup: bool = True) -> None:
        self._set_notice(text, "error", 7000)
        if popup:
            QMessageBox.critical(self, "Ошибка", text)

    def _status_style(self, state: str) -> str:
        colors = {
            "online": "#12a150",
            "offline": "#d32f2f",
            "starting": "#f39c12",
            "stopping": "#f39c12",
            "error": "#d32f2f",
        }
        return f"font-size:24px; font-weight:700; color:{colors.get(state, '#444444')};"

    def _set_status(self, state: str, text: Optional[str] = None) -> None:
        self._current_state = state
        self.status_label.setStyleSheet(self._status_style(state))
        self.status_label.setText(text or f"Статус: {state}")

    def _provider_style(self, state: str) -> tuple[str, str]:
        mapping = {
            "online": ("● online", "#22c55e"),
            "starting": ("● starting", "#f59e0b"),
            "disabled": ("● offline", "#ef4444"),
            "error": ("● error", "#ef4444"),
            "offline": ("● offline", "#ef4444"),
            "unknown": ("● нет данных", "#94a3b8"),
        }
        return mapping.get(state, mapping["unknown"])

    def _set_provider_status(self, key: str, state: str) -> None:
        label = self.provider_status_labels.get(key)
        if label is None:
            return
        text, color = self._provider_style(state)
        label.setText(text)
        label.setStyleSheet(f"font-size:12px; font-weight:800; color:{color};")

    def _extract_provider_state(self, raw: Any) -> str:
        if isinstance(raw, bool):
            return "online" if raw else "offline"
        if isinstance(raw, str):
            value = raw.strip().lower()
            return value if value in {"online", "offline", "starting", "disabled", "error"} else "unknown"
        if isinstance(raw, dict):
            status = str(raw.get("status", "")).strip().lower()
            if status in {"online", "offline", "starting", "disabled", "error"}:
                return status
            connected = raw.get("connected")
            enabled = raw.get("enabled")
            if connected is True:
                return "online"
            if enabled is False:
                return "disabled"
        return "unknown"

    def _provider_config_candidates(self) -> list[Path]:
        candidates = [
            self.project_root / "backend" / "config.yaml",
            self.project_root.parent / "backend" / "config.yaml",
            Path.cwd() / "backend" / "config.yaml",
            Path.cwd() / "config.yaml",
            Path(__file__).resolve().with_name("config.yaml"),
        ]
        uniq: list[Path] = []
        seen: set[str] = set()
        for path in candidates:
            norm = str(path.resolve()) if path.exists() else str(path)
            if norm in seen:
                continue
            seen.add(norm)
            uniq.append(path)
        return uniq

    def _load_provider_enabled_flags(self) -> dict[str, bool]:
        defaults = {key: False for key, _title in self.PROVIDERS}
        for path in self._provider_config_candidates():
            if not path.exists():
                continue
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                providers = data.get("providers") or {}
                if not isinstance(providers, dict):
                    continue
                result = defaults.copy()
                for key, _title in self.PROVIDERS:
                    raw = providers.get(key)
                    if isinstance(raw, dict):
                        result[key] = bool(raw.get("enabled", False))
                return result
            except Exception:
                continue
        return defaults

    def _refresh_provider_statuses(self) -> None:
        backend_online = self._is_online()
        enabled_flags = self._load_provider_enabled_flags()

        for key, _title in self.PROVIDERS:
            enabled = bool(enabled_flags.get(key, False))
            state = "online" if backend_online and enabled else "offline"
            self._set_provider_status(key, state)

    def _append_obs_log(self, text: str) -> None:
        current = self.obs_actions_log.toPlainText().strip()
        lines = current.splitlines() if current else []
        lines.append(text)
        lines = lines[-200:]
        self.obs_actions_log.setPlainText("\n".join(lines))
        cursor = self.obs_actions_log.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.obs_actions_log.setTextCursor(cursor)

    def _checked_names_for_kind(self, scene_name: str, kind: str) -> list[str]:
        scene_name = str(scene_name or "").strip()
        if not scene_name:
            return []
        if kind == "script":
            raw = self._saved_script_states().get(scene_name, [])
        else:
            raw = self._saved_scene_states().get(scene_name, [])
        return raw if isinstance(raw, list) else []

    def _set_named_item_saved_state(self, scene_name: str, name: str, kind: str, enabled: bool) -> None:
        scene_name = str(scene_name or "").strip()
        name = str(name or "").strip()
        if not scene_name or not name:
            return

        if kind == "script":
            saved = self._saved_script_states()
        else:
            saved = self._saved_scene_states()

        current = [str(x) for x in (saved.get(scene_name, []) or [])]
        if enabled:
            if name not in current:
                current.append(name)
        else:
            current = [x for x in current if x != name]

        saved[scene_name] = current
        if kind == "script":
            self._save_script_states_map(saved)
        else:
            self._save_scene_states_map(saved)

    def _is_named_item_enabled(self, scene_name: str, name: str, kind: str) -> bool:
        return str(name or "").strip() in set(self._checked_names_for_kind(scene_name, kind))

    def _catalog_scene_filter_value(self) -> str:
        text = self.catalog_scene_filter.currentText().strip() if hasattr(self, "catalog_scene_filter") else ""
        return "" if text in {"", "Все сцены"} else text

    def _catalog_kind_filter_value(self) -> str:
        text = self.catalog_kind_filter.currentText().strip() if hasattr(self, "catalog_kind_filter") else ""
        if text == "Только источники":
            return "source"
        if text == "Только скрипты":
            return "script"
        return ""

    def _catalog_state_filter_value(self) -> str:
        text = self.catalog_state_filter.currentText().strip() if hasattr(self, "catalog_state_filter") else ""
        if text == "Только включённые":
            return "enabled"
        if text == "Только выключенные":
            return "disabled"
        return ""

    def _refresh_catalog_scene_filter(self) -> None:
        if not hasattr(self, "catalog_scene_filter"):
            return
        current = self.catalog_scene_filter.currentText().strip()
        self.catalog_scene_filter.blockSignals(True)
        self.catalog_scene_filter.clear()
        self.catalog_scene_filter.addItem("Все сцены")
        for scene_name in self.obs_inventory.keys():
            self.catalog_scene_filter.addItem(scene_name)
        index = self.catalog_scene_filter.findText(current)
        self.catalog_scene_filter.setCurrentIndex(index if index >= 0 else 0)
        self.catalog_scene_filter.blockSignals(False)

    def _refresh_catalog_tree(self) -> None:
        if not hasattr(self, "catalog_tree"):
            return

        self._refresh_catalog_scene_filter()
        search = (self.catalog_search_input.text() or "").strip().lower()
        scene_filter = self._catalog_scene_filter_value()
        kind_filter = self._catalog_kind_filter_value()
        state_filter = self._catalog_state_filter_value()

        self._updating_catalog = True
        self.catalog_tree.clear()
        self.catalog_row_items.clear()

        for scene_name in sorted(self.obs_inventory.keys(), key=str.lower):
            if scene_filter and scene_name != scene_filter:
                continue
            scene_sources = sorted(self.obs_inventory.get(scene_name, []), key=str.lower)
            for name in scene_sources:
                kind = self._get_item_kind(name)
                if kind_filter and kind != kind_filter:
                    continue
                enabled = self._is_named_item_enabled(scene_name, name, kind)
                if state_filter == "enabled" and not enabled:
                    continue
                if state_filter == "disabled" and enabled:
                    continue
                text_blob = f"{scene_name} {name} {kind}".lower()
                if search and search not in text_blob:
                    continue

                type_icon, type_label = self._infer_obs_item_type(name, kind)
                item = QTreeWidgetItem([
                    scene_name,
                    name,
                    self._category_badge(kind),
                    f"{type_icon} {type_label}",
                    "",
                ])
                item.setFlags(item.flags() | Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                item.setCheckState(4, Qt.Checked if enabled else Qt.Unchecked)
                item.setData(0, Qt.UserRole, scene_name)
                item.setData(1, Qt.UserRole, name)
                item.setData(2, Qt.UserRole, kind)
                item.setData(4, Qt.UserRole, enabled)
                for col in range(5):
                    item.setTextAlignment(col, Qt.AlignCenter)
                self.catalog_tree.addTopLevelItem(item)
                self.catalog_row_items.append(item)

        self.catalog_tree.sortItems(0, Qt.AscendingOrder)
        self._updating_catalog = False
        self._refresh_catalog_stats()

    def _refresh_catalog_stats(self) -> None:
        if not hasattr(self, "catalog_tree"):
            return
        total = self.catalog_tree.topLevelItemCount()
        checked = 0
        for i in range(total):
            if self.catalog_tree.topLevelItem(i).checkState(4) == Qt.Checked:
                checked += 1
        selected = len(self.catalog_tree.selectedItems())
        self.catalog_stats_label.setText(f"Строк: {total} / отмечено: {checked} / выделено: {selected}")

    def on_catalog_filters_changed(self, *args) -> None:
        self._refresh_catalog_tree()

    def _catalog_selected_rows(self) -> list[QTreeWidgetItem]:
        return [item for item in self.catalog_tree.selectedItems() if item is not None]

    def _sync_named_item_in_lists(self, scene_name: str, name: str, kind: str, enabled: bool) -> None:
        if kind == "script":
            if scene_name == self._current_script_scene_name() and name in self.script_items_by_name:
                item = self.script_items_by_name[name]
                self._updating_scripts = True
                self._set_source_item_checked(item, enabled)
                self._set_source_item_applied_state(item, enabled)
                self._updating_scripts = False
                self._refresh_script_status_labels()
                self._refresh_scripts_summary_panel()
        else:
            if scene_name == self._current_scene_name() and name in self.source_items_by_name:
                item = self.source_items_by_name[name]
                self._updating_sources = True
                self._set_source_item_checked(item, enabled)
                self._set_source_item_applied_state(item, enabled)
                self._updating_sources = False
                self._refresh_source_status_labels()
                self._refresh_browser_sources_panel()

    def on_catalog_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating_catalog or column != 4:
            return

        scene_name = str(item.data(0, Qt.UserRole) or item.text(0)).strip()
        name = str(item.data(1, Qt.UserRole) or item.text(1)).strip()
        kind = str(item.data(2, Qt.UserRole) or "source").strip()
        checked = item.checkState(4) == Qt.Checked
        previous_state = bool(item.data(4, Qt.UserRole))

        self._set_named_item_saved_state(scene_name, name, kind, checked)
        self._sync_named_item_in_lists(scene_name, name, kind, checked)

        if self._is_online() and self.obs_connected:
            ok, message = self._apply_named_item_visibility(scene_name, name, checked)
            if not ok:
                self._updating_catalog = True
                item.setCheckState(4, Qt.Checked if previous_state else Qt.Unchecked)
                self._updating_catalog = False
                self._set_named_item_saved_state(scene_name, name, kind, previous_state)
                self._sync_named_item_in_lists(scene_name, name, kind, previous_state)
                self._show_error(f"Не удалось переключить элемент: {name}\n\n{message}", popup=False)
                self._refresh_catalog_stats()
                return
        item.setData(4, Qt.UserRole, checked)
        self._set_notice(
            f"{scene_name} → {name}: {'включён' if checked else 'скрыт'}",
            "success",
            1400,
        )
        self._refresh_catalog_stats()

    def _set_catalog_selected_visible(self, visible: bool) -> None:
        selected = self._catalog_selected_rows()
        if not selected:
            self._show_warning("Сначала выдели строки в каталоге.")
            return
        if not self._is_online():
            self._show_warning("Сначала запусти backend.")
            return
        if not self.obs_connected:
            self._show_warning("OBS не подключён. Нажми «Подключить OBS».")
            return

        success_count = 0
        error_count = 0
        for item in selected:
            scene_name = str(item.data(0, Qt.UserRole) or item.text(0)).strip()
            name = str(item.data(1, Qt.UserRole) or item.text(1)).strip()
            kind = str(item.data(2, Qt.UserRole) or "source").strip()
            ok, message = self._apply_named_item_visibility(scene_name, name, visible)
            if ok:
                success_count += 1
                self._updating_catalog = True
                item.setCheckState(4, Qt.Checked if visible else Qt.Unchecked)
                self._updating_catalog = False
                item.setData(3, Qt.UserRole, visible)
                self._set_named_item_saved_state(scene_name, name, kind, visible)
                self._sync_named_item_in_lists(scene_name, name, kind, visible)
            else:
                error_count += 1
                self._append_obs_log(f"[{scene_name}] Ошибка переключения {name}: {message}")

        self._refresh_catalog_stats()
        self._show_info(f"Готово. Успешно: {success_count}, ошибок: {error_count}")

    def on_catalog_show_selected_clicked(self) -> None:
        self._set_catalog_selected_visible(True)

    def on_catalog_hide_selected_clicked(self) -> None:
        self._set_catalog_selected_visible(False)

    def on_catalog_refresh_checked_clicked(self) -> None:
        if not self._is_online():
            self._show_warning("Сначала запусти backend.")
            return
        if not self.obs_connected:
            self._show_warning("OBS не подключён. Нажми «Подключить OBS».")
            return

        checked_items = []
        for i in range(self.catalog_tree.topLevelItemCount()):
            item = self.catalog_tree.topLevelItem(i)
            if item.checkState(4) == Qt.Checked:
                checked_items.append(item)

        if not checked_items:
            self._show_warning("В каталоге нет отмеченных элементов.")
            return

        success_count = 0
        error_count = 0
        seen = set()
        for item in checked_items:
            name = str(item.data(1, Qt.UserRole) or item.text(1)).strip()
            if name in seen:
                continue
            seen.add(name)
            ok, data = self._http_post_json_data("/api/obs/refresh-browser-source", {"source_name": name})
            if ok and isinstance(data, dict) and data.get("ok"):
                success_count += 1
            else:
                error_count += 1

        self._show_info(f"Обновление отмеченных элементов завершено. Успешно: {success_count}, ошибок: {error_count}")

    def _catalog_selected_names_by_kind(self, target_kind: str | None = None) -> list[str]:
        names: list[str] = []
        for item in self._catalog_selected_rows():
            kind = str(item.data(2, Qt.UserRole) or "source").strip()
            if target_kind and kind != target_kind:
                continue
            name = str(item.data(1, Qt.UserRole) or item.text(1)).strip()
            if name and name not in names:
                names.append(name)
        return names

    def on_catalog_move_selected_to_scripts_clicked(self) -> None:
        names = self._catalog_selected_names_by_kind()
        if not names:
            self._show_warning("Сначала выдели строки каталога, которые нужно считать скриптами.")
            return
        self._move_items_to_kind(names, "script")

    def on_catalog_move_selected_to_sources_clicked(self) -> None:
        names = self._catalog_selected_names_by_kind()
        if not names:
            self._show_warning("Сначала выдели строки каталога, которые нужно считать обычными источниками.")
            return
        self._move_items_to_kind(names, "source")

    def _apply_commercial_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #0f172a;
                color: #e5e7eb;
                font-size: 13px;
            }
            QGroupBox {
                border: 1px solid #243041;
                border-radius: 14px;
                margin-top: 12px;
                padding-top: 12px;
                background: #111827;
                font-weight: 700;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 6px;
                color: #f8fafc;
            }
            QPushButton {
                background: #1e293b;
                color: #e5e7eb;
                border: 1px solid #334155;
                border-radius: 10px;
                padding: 4px 10px;
                font-weight: 600;
            }
            QPushButton:hover { background: #273449; }
            QPushButton:pressed { background: #334155; }
            QPushButton:disabled { color: #64748b; background: #0f172a; }
            QLineEdit, QComboBox, QListWidget, QTreeWidget, QPlainTextEdit, QTextEdit {
                background: #0b1220;
                color: #e5e7eb;
                border: 1px solid #243041;
                border-radius: 10px;
                padding: 4px 8px;
            }
            QTreeWidget {
                show-decoration-selected: 1;
                alternate-background-color: #111a2d;
            }
            QListWidget::item, QTreeWidget::item {
                height: 28px;
                padding: 3px 6px;
            }
            QListWidget::item:selected, QTreeWidget::item:selected {
                background: #1d4ed8;
                color: white;
            }
            QHeaderView::section {
                background: #172033;
                color: #cbd5e1;
                border: 0;
                padding: 8px;
                font-weight: 700;
                text-align: center;
            }
            QTabBar::tab {
                background: #111827;
                color: #cbd5e1;
                padding: 8px 14px;
                border: 1px solid #243041;
                border-bottom: none;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background: #1d4ed8;
                color: white;
            }
            QLabel { color: #e5e7eb; }
            QWidget#noticeCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #11213d, stop:1 #0b1220);
                border: 1px solid #2563eb;
                border-radius: 14px;
            }
            QLabel#noticeTitle {
                color: #eff6ff;
                font-size: 14px;
                font-weight: 800;
            }
            QLabel#noticeDetail {
                color: #bfdbfe;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#noticeIcon {
                color: #60a5fa;
                background: #0b2545;
                border: 1px solid #1d4ed8;
                border-radius: 13px;
                font-size: 18px;
                font-weight: 900;
            }
            QLabel#noticeBadge {
                background: #0b2545;
                color: #dbeafe;
                border: 1px solid #1d4ed8;
                border-radius: 11px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: 900;
                letter-spacing: 1px;
            }
            """
        )

    def _saved_script_library(self) -> list[dict[str, Any]]:
        data = self._load_settings_dict()
        raw = data.get("obs_script_library", [])
        return raw if isinstance(raw, list) else []

    def _save_script_library(self, items: list[dict[str, Any]]) -> None:
        data = self._load_settings_dict()
        data["obs_script_library"] = items
        self._save_settings_dict(data)

    def _detect_script_file_type(self, file_path: str) -> tuple[str, str]:
        suffix = Path(file_path).suffix.lower()
        if suffix == ".py":
            return "🐍 Python", "Требует добавления в OBS вручную"
        if suffix == ".lua":
            return "🌙 Lua", "Требует добавления в OBS вручную"
        if suffix in {".html", ".htm"}:
            return "🌐 HTML", "Подходит для Browser Source"
        if suffix in {".js", ".css"}:
            return "🧩 Web asset", "Используй вместе с HTML"
        if suffix in {".ps1", ".bat", ".cmd"}:
            return "🖥 Автоскрипт", "Запускается вне OBS"
        return "📄 Файл", "Добавлен в библиотеку"

    def _selected_script_library_entry(self) -> dict[str, Any] | None:
        item = self.script_library_tree.currentItem()
        if item is None:
            return None
        data = item.data(0, Qt.UserRole)
        return data if isinstance(data, dict) else None

    def _update_script_library_buttons(self) -> None:
        has_selection = self._selected_script_library_entry() is not None
        self.btn_open_script_location.setEnabled(has_selection)
        self.btn_copy_script_path.setEnabled(has_selection)
        self.btn_remove_script_file.setEnabled(has_selection)

    def _refresh_script_library_tree(self) -> None:
        if not hasattr(self, "script_library_tree"):
            return
        entries = sorted(self._saved_script_library(), key=lambda x: str(x.get("name", "")).lower())
        self._updating_script_library = True
        self.script_library_tree.clear()
        for entry in entries:
            name = str(entry.get("name", "")).strip()
            file_path = str(entry.get("path", "")).strip()
            file_type = str(entry.get("type", "📄 Файл")).strip()
            status = str(entry.get("status", "Добавлен в библиотеку")).strip()
            row = QTreeWidgetItem([name, file_type, file_path, status])
            for col in range(4):
                row.setTextAlignment(col, Qt.AlignCenter)
            row.setData(0, Qt.UserRole, entry)
            self.script_library_tree.addTopLevelItem(row)
        self._updating_script_library = False
        self.script_library_hint.setText(f"Файлов в библиотеке: {self.script_library_tree.topLevelItemCount()}")
        self._update_script_library_buttons()

    def on_add_script_file_clicked(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Добавить OBS-скрипт или оверлей",
            str(Path.home()),
            "Скрипты и оверлеи (*.py *.lua *.html *.htm *.js *.css *.ps1 *.bat *.cmd);;Все файлы (*.*)",
        )
        if not files:
            return
        items = self._saved_script_library()
        existing_paths = {str(item.get("path", "")).strip().lower() for item in items}
        added = 0
        for file_path in files:
            normalized = str(Path(file_path).resolve())
            if normalized.lower() in existing_paths:
                continue
            file_type, status = self._detect_script_file_type(normalized)
            items.append({
                "name": Path(normalized).stem,
                "path": normalized,
                "type": file_type,
                "status": status,
            })
            existing_paths.add(normalized.lower())
            added += 1
        self._save_script_library(items)
        self._refresh_script_library_tree()
        if added:
            self._set_notice(f"В библиотеку добавлено файлов: {added}", "success", 1800)

    def on_remove_script_file_clicked(self) -> None:
        entry = self._selected_script_library_entry()
        if not entry:
            self._show_warning("Сначала выбери файл в библиотеке скриптов.")
            return
        path_value = str(entry.get("path", "")).strip()
        items = [item for item in self._saved_script_library() if str(item.get("path", "")).strip() != path_value]
        self._save_script_library(items)
        self._refresh_script_library_tree()
        self._set_notice("Файл удалён из библиотеки.", "info", 1500)

    def on_copy_script_path_clicked(self) -> None:
        entry = self._selected_script_library_entry()
        if not entry:
            self._show_warning("Сначала выбери файл в библиотеке скриптов.")
            return
        QApplication.clipboard().setText(str(entry.get("path", "")).strip())
        self._set_notice("Путь скопирован в буфер обмена.", "success", 1500)

    def on_open_script_location_clicked(self) -> None:
        entry = self._selected_script_library_entry()
        if not entry:
            self._show_warning("Сначала выбери файл в библиотеке скриптов.")
            return
        file_path = Path(str(entry.get("path", "")).strip())
        if not file_path.exists():
            self._show_warning("Файл не найден по сохранённому пути.")
            return
        try:
            if os.name == "nt":
                os.startfile(str(file_path.parent))
            else:
                webbrowser.open(file_path.parent.as_uri())
        except Exception as e:
            self._show_error(f"Не удалось открыть папку файла:\n{e}", popup=False)

    def _saved_scene_states(self) -> dict[str, list[str]]:
        data = self._load_settings_dict()
        raw = data.get("obs_scene_enabled_sources", {})
        return raw if isinstance(raw, dict) else {}

    def _save_scene_states_map(self, scene_map: dict[str, list[str]]) -> None:
        data = self._load_settings_dict()
        data["obs_scene_enabled_sources"] = scene_map
        self._save_settings_dict(data)

    def _saved_script_states(self) -> dict[str, list[str]]:
        data = self._load_settings_dict()
        raw = data.get("obs_scene_enabled_scripts", {})
        return raw if isinstance(raw, dict) else {}

    def _save_script_states_map(self, scene_map: dict[str, list[str]]) -> None:
        data = self._load_settings_dict()
        data["obs_scene_enabled_scripts"] = scene_map
        self._save_settings_dict(data)

    def _item_kinds_map(self) -> dict[str, str]:
        data = self._load_settings_dict()
        raw = data.get("obs_item_kinds", {})
        return raw if isinstance(raw, dict) else {}

    def _save_item_kinds_map(self, kind_map: dict[str, str]) -> None:
        data = self._load_settings_dict()
        data["obs_item_kinds"] = kind_map
        self._save_settings_dict(data)

    def _guess_item_kind(self, name: str) -> str:
        low = (name or "").strip().lower()
        script_keywords = (
            "script", "скрипт", "overlay", "оверлей", "alert", "алерт", "donat", "donation",
            "widget", "виджет", "banner", "баннер", "chat", "чат", "browser", "брауз",
            "html", "реклама", "ad", "ticker", "тикер", "goal", "цель", "notify", "уведом"
        )
        return "script" if any(key in low for key in script_keywords) else "source"

    def _get_item_kind(self, name: str) -> str:
        kind_map = self._item_kinds_map()
        kind = str(kind_map.get(name, "")).strip().lower()
        if kind in {"source", "script"}:
            return kind
        guessed = self._guess_item_kind(name)
        kind_map[name] = guessed
        self._save_item_kinds_map(kind_map)
        return guessed

    def _set_item_kind(self, name: str, kind: str) -> None:
        kind = "script" if str(kind).strip().lower() == "script" else "source"
        kind_map = self._item_kinds_map()
        kind_map[name] = kind
        self._save_item_kinds_map(kind_map)

    def _infer_obs_item_type(self, name: str, kind: str | None = None) -> tuple[str, str]:
        low = (name or "").strip().lower()
        current_kind = kind or self._get_item_kind(name)
        if current_kind == "script":
            return "⚙️", "Скрипт"
        if any(key in low for key in ("browser", "брауз", "chat", "чат", "overlay", "оверлей", "html", "alert", "donat", "widget", "banner", "баннер")):
            return "🌐", "Browser"
        if any(key in low for key in ("cam", "camera", "webcam", "вебк", "камера")):
            return "🎥", "Камера"
        if any(key in low for key in ("audio", "mic", "micro", "звук", "муз", "music", "tts")):
            return "🔊", "Аудио"
        if any(key in low for key in ("image", "logo", "png", "jpg", "jpeg", "рамка", "frame", "img")):
            return "🖼", "Изображение"
        if any(key in low for key in ("text", "label", "title", "текст", "заголов")):
            return "🔤", "Текст"
        if any(key in low for key in ("group", "scene", "группа", "сцена")):
            return "📦", "Группа"
        if any(key in low for key in ("media", "video", "movie", "clip", "ролик", "видео")):
            return "🎞", "Медиа"
        return "🔹", "Элемент"

    def _category_badge(self, kind: str) -> str:
        return "🟣 Скрипт" if kind == "script" else "🟢 Источник"

    def _display_name_with_icons(self, name: str, kind: str) -> str:
        icon, label = self._infer_obs_item_type(name, kind)
        return f"{icon}  {name}"

    def _ensure_item_kinds_for_inventory(self) -> None:
        kind_map = self._item_kinds_map()
        changed = False
        for scene_sources in self.obs_inventory.values():
            for name in scene_sources:
                if name not in kind_map:
                    kind_map[name] = self._guess_item_kind(name)
                    changed = True
        if changed:
            self._save_item_kinds_map(kind_map)

    def _current_scene_name(self) -> str:
        item = self.scene_list.currentItem()
        return item.text().strip() if item is not None else ""

    def _visible_source_items(self) -> list[QListWidgetItem]:
        return [self.source_list.item(i) for i in range(self.source_list.count()) if not self.source_list.item(i).isHidden()]

    def _all_source_items(self) -> list[QListWidgetItem]:
        return [self.source_list.item(i) for i in range(self.source_list.count())]

    def _checked_source_names(self) -> list[str]:
        names: list[str] = []
        for item in self._all_source_items():
            if item.checkState() == Qt.Checked:
                names.append(item.data(Qt.UserRole) or item.text())
        return names

    def _selected_source_names(self) -> list[str]:
        names: list[str] = []
        for item in self.source_list.selectedItems():
            if item.isHidden():
                continue
            names.append(item.data(Qt.UserRole) or item.text())
        return names

    def _current_script_scene_name(self) -> str:
        item = self.script_scene_list.currentItem()
        return item.text().strip() if item is not None else ""

    def _visible_script_items(self) -> list[QListWidgetItem]:
        return [self.script_list.item(i) for i in range(self.script_list.count()) if not self.script_list.item(i).isHidden()]

    def _all_script_items(self) -> list[QListWidgetItem]:
        return [self.script_list.item(i) for i in range(self.script_list.count())]

    def _checked_script_names(self) -> list[str]:
        names: list[str] = []
        for item in self._all_script_items():
            if item.checkState() == Qt.Checked:
                names.append(item.data(Qt.UserRole) or item.text())
        return names

    def _selected_script_names(self) -> list[str]:
        names: list[str] = []
        for item in self.script_list.selectedItems():
            if item.isHidden():
                continue
            names.append(item.data(Qt.UserRole) or item.text())
        return names

    def _save_current_scene_selection(self) -> None:
        scene_name = self._current_scene_name()
        if not scene_name or self._loading_scene or self._updating_sources:
            return

        saved = self._saved_scene_states()
        saved[scene_name] = self._checked_source_names()
        self._save_scene_states_map(saved)
        self._refresh_source_status_labels()
        self._refresh_browser_sources_panel()
        self._refresh_catalog_tree()

    def _load_scene_selection_from_saved(self, scene_name: str) -> list[str]:
        saved = self._saved_scene_states()
        raw = saved.get(scene_name, [])
        return raw if isinstance(raw, list) else []

    def _save_current_script_selection(self) -> None:
        scene_name = self._current_script_scene_name()
        if not scene_name or self._loading_script_scene or self._updating_scripts:
            return

        saved = self._saved_script_states()
        saved[scene_name] = self._checked_script_names()
        self._save_script_states_map(saved)
        self._refresh_script_status_labels()
        self._refresh_scripts_summary_panel()
        self._refresh_catalog_tree()

    def _load_script_scene_selection_from_saved(self, scene_name: str) -> list[str]:
        saved = self._saved_script_states()
        raw = saved.get(scene_name, [])
        return raw if isinstance(raw, list) else []

    def _http_post_json(self, path: str, payload: dict[str, Any]) -> tuple[bool, str]:
        import requests

        url = f"http://127.0.0.1:8765{path}"
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

    def _http_post_json_data(self, path: str, payload: dict[str, Any]) -> tuple[bool, Any]:
        import requests

        url = f"http://127.0.0.1:8765{path}"
        try:
            session = requests.Session()
            session.trust_env = False
            resp = session.post(url, json=payload, timeout=5)
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
            resp = session.get(url, timeout=4)
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
            self.obs_status_label.setStyleSheet("font-size:12px; font-weight:800; color:#22c55e;")
        else:
            self.obs_status_label.setText(text or "OBS: не подключён")
            self.obs_status_label.setStyleSheet("font-size:12px; font-weight:800; color:#94a3b8;")

    def _safe_get_logs(self) -> str:
        try:
            if hasattr(self.backend, "get_logs"):
                return str(self.backend.get_logs())
            if hasattr(self.backend, "get_logs_text"):
                return str(self.backend.get_logs_text())
        except Exception as e:
            return f"[ui-error] Не удалось получить лог: {e}\n"
        return ""

    def _set_logs_text(self, text: str) -> None:
        text = text or ""
        if text == self._last_logs_text:
            return
        self.logs_box.setPlainText(text)
        self._last_logs_text = text
        cursor = self.logs_box.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.logs_box.setTextCursor(cursor)

    def _is_online(self) -> bool:
        try:
            return bool(self.backend.is_running())
        except Exception:
            return False

    def _refresh_obs_connection_state(self) -> None:
        if not self._is_online():
            self.obs_connected = False
            self._update_obs_status_label(False, "OBS: backend offline")
            return

        ok, data = self._http_get_json_data("/api/obs/status")
        if not ok or not isinstance(data, dict):
            self.obs_connected = False
            self._update_obs_status_label(False, "OBS: статус недоступен")
            return

        connected = bool(data.get("connected", False))
        self.obs_connected = connected
        if connected:
            version = data.get("version", {}) or {}
            obs_ver = version.get("obs_version", "unknown")
            current_scene = str(data.get("current_scene", "") or "").strip()
            text = f"OBS: подключён ({obs_ver})"
            if current_scene:
                text += f" | Сцена: {current_scene}"
            self._update_obs_status_label(True, text)
        else:
            self._update_obs_status_label(False, "OBS: не подключён")

    def _update_buttons_state(self) -> None:
        online = self._is_online()
        obs_ready = online and self.obs_connected
        scene_loaded = bool(self.scene_list.count() > 0)
        has_sources = bool(self.source_list.count() > 0)
        has_checked = bool(self._checked_source_names())
        has_selected = bool(self._selected_source_names())

        script_scene_loaded = bool(self.script_scene_list.count() > 0)
        has_scripts = bool(self.script_list.count() > 0)
        has_checked_scripts = bool(self._checked_script_names())
        has_selected_scripts = bool(self._selected_script_names())

        self.btn_start.setEnabled(not online)
        self.btn_stop.setEnabled(online)
        self.btn_restart.setEnabled(online)
        self.btn_overlay.setEnabled(online)
        self.btn_control.setEnabled(online)
        self.btn_refresh.setEnabled(True)

        self.btn_send_test_alert.setEnabled(online)
        self.btn_obs_connect.setEnabled(online)
        self.btn_obs_reload_inventory.setEnabled(obs_ready)

        self.scene_list.setEnabled(scene_loaded)
        self.source_list.setEnabled(scene_loaded)
        self.source_search_input.setEnabled(scene_loaded)

        self.btn_scene_apply.setEnabled(obs_ready and scene_loaded and has_sources)
        self.btn_scene_all_on.setEnabled(scene_loaded and has_sources)
        self.btn_scene_all_off.setEnabled(scene_loaded and has_sources)
        self.btn_scene_show_selected.setEnabled(obs_ready and has_selected)
        self.btn_scene_hide_selected.setEnabled(obs_ready and has_selected)
        self.btn_scene_refresh_checked.setEnabled(obs_ready and has_checked)
        self.btn_move_selected_to_scripts.setEnabled(has_selected)
        self.btn_refresh_all_browser_sources.setEnabled(obs_ready and bool(self.obs_inventory))

        self.script_scene_list.setEnabled(script_scene_loaded)
        self.script_list.setEnabled(script_scene_loaded)
        self.script_search_input.setEnabled(script_scene_loaded)

        self.btn_script_apply.setEnabled(obs_ready and script_scene_loaded and has_scripts)
        self.btn_script_all_on.setEnabled(script_scene_loaded and has_scripts)
        self.btn_script_all_off.setEnabled(script_scene_loaded and has_scripts)
        self.btn_script_show_selected.setEnabled(obs_ready and has_selected_scripts)
        self.btn_script_hide_selected.setEnabled(obs_ready and has_selected_scripts)
        self.btn_script_refresh_checked.setEnabled(obs_ready and has_checked_scripts)
        self.btn_move_selected_to_sources.setEnabled(has_selected_scripts)

        self.btn_apply_ads.setEnabled(True)
        self.btn_save_settings.setEnabled(True)

    def _load_settings_dict(self) -> dict[str, Any]:
        return self.config_manager.load()

    def _save_settings_dict(self, data: dict[str, Any]) -> None:
        self.config_manager.save(data)

    def _apply_settings_to_form(self, data: dict[str, Any]) -> None:
        self.chk_show_ads.setChecked(bool(data.get("show_site_ads", False)))
        self.input_ad_title.setText(str(data.get("ad_title", "")))
        self.input_ad_line2.setText(str(data.get("ad_line2", "")))
        self.input_ad_line3.setText(str(data.get("ad_line3", "")))
        self.input_music_volume.setText(self._normalize_volume_text(str(data.get("music_volume", "0.35")), "0.35"))
        self.input_tts_volume.setText(self._normalize_volume_text(str(data.get("tts_volume", "1.00")), "1.00"))
        self._set_tts_voice_value(str(data.get("tts_voice", "default")))
        self.obs_host_input.setText(str(data.get("obs_host", "127.0.0.1")))
        self.obs_port_input.setText(str(data.get("obs_port", "4455")))
        self.obs_password_input.setText(str(data.get("obs_password", "")))

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
            "obs_host": self.obs_host_input.text().strip() or "127.0.0.1",
            "obs_port": self.obs_port_input.text().strip() or "4455",
            "obs_password": self.obs_password_input.text(),
            "obs_scene_enabled_sources": self._saved_scene_states(),
            "obs_scene_enabled_scripts": self._saved_script_states(),
            "obs_item_kinds": self._item_kinds_map(),
            "obs_script_library": self._saved_script_library(),
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
        self._apply_settings_to_form(self._load_settings_dict())

    # ------------------------------------------------------------------
    # Scene/source UI
    # ------------------------------------------------------------------

    def _set_source_item_checked(self, item: QListWidgetItem, checked: bool) -> None:
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def _set_source_item_applied_state(self, item: QListWidgetItem, checked: bool) -> None:
        item.setData(Qt.UserRole + 1, bool(checked))

    def _get_source_item_applied_state(self, item: QListWidgetItem) -> bool:
        value = item.data(Qt.UserRole + 1)
        if isinstance(value, bool):
            return value
        return item.checkState() == Qt.Checked

    def _apply_named_item_visibility(self, scene_name: str, source_name: str, checked: bool) -> tuple[bool, str]:
        if not self._is_online():
            return False, "Backend сейчас offline."
        if not self.obs_connected:
            return False, "OBS не подключён."
        if not scene_name:
            return False, "Сцена не выбрана."

        path = "/api/obs/show-source" if checked else "/api/obs/hide-source"
        action_name = "Показать" if checked else "Скрыть"
        ok, data = self._http_post_json_data(path, {"scene_name": scene_name, "source_name": source_name})
        if ok and isinstance(data, dict) and data.get("ok"):
            self._append_obs_log(f"[{scene_name}] {action_name}: {source_name}")
            return True, ""

        message = data.get("message", "ошибка") if isinstance(data, dict) else str(data)
        self._append_obs_log(f"[{scene_name}] Ошибка {action_name.lower()} {source_name}: {message}")
        return False, message

    def _apply_single_source_visibility(self, item: QListWidgetItem, checked: bool) -> tuple[bool, str]:
        scene_name = self._current_scene_name()
        source_name = str(item.data(Qt.UserRole) or item.text())
        ok, message = self._apply_named_item_visibility(scene_name, source_name, checked)
        if ok:
            self._set_source_item_applied_state(item, checked)
        return ok, message

    def _apply_single_script_visibility(self, item: QListWidgetItem, checked: bool) -> tuple[bool, str]:
        scene_name = self._current_script_scene_name()
        source_name = str(item.data(Qt.UserRole) or item.text())
        ok, message = self._apply_named_item_visibility(scene_name, source_name, checked)
        if ok:
            self._set_source_item_applied_state(item, checked)
        return ok, message

    def _sync_current_scene_to_obs(self, show_notice: bool = True) -> tuple[int, int, list[str]]:
        scene_name = self._current_scene_name()
        success_count = 0
        error_count = 0
        error_lines: list[str] = []

        for item in self._all_source_items():
            source_name = str(item.data(Qt.UserRole) or item.text())
            checked = item.checkState() == Qt.Checked
            ok, message = self._apply_single_source_visibility(item, checked)
            if ok:
                success_count += 1
            else:
                error_count += 1
                error_lines.append(f"{source_name}: {message}")

        self._save_current_scene_selection()

        if show_notice:
            if error_count == 0:
                self._show_info(f"Сцена синхронизирована: {scene_name}. Успешно: {success_count}")
            else:
                self._show_error(
                    f"Сцена синхронизирована: {scene_name}. Успешно: {success_count}, ошибок: {error_count}.\n\n"
                    + "\n".join(error_lines[:10]),
                    popup=False,
                )

        return success_count, error_count, error_lines

    def _rebuild_scene_sources_ui(self, scene_name: str) -> None:
        self._updating_sources = True
        self.source_list.clear()
        self.source_items_by_name.clear()

        scene_name = (scene_name or "").strip()
        self.current_scene_label.setText(f"Источники сцены: {scene_name or '—'}")

        if not scene_name:
            self.source_stats_label.setText("0 / 0")
            self.browser_sources_box.setPlainText("Сначала загрузи сцены и выбери одну из них.")
            self._updating_sources = False
            self._update_buttons_state()
            return

        sources = self.obs_inventory.get(scene_name, [])
        saved_enabled = set(self._load_scene_selection_from_saved(scene_name))

        for source_name in sources:
            if self._get_item_kind(source_name) != "source":
                continue
            item = QListWidgetItem(self._display_name_with_icons(source_name, "source"))
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            item.setData(Qt.UserRole, source_name)
            checked = source_name in saved_enabled
            self._set_source_item_checked(item, checked)
            self._set_source_item_applied_state(item, checked)
            self.source_list.addItem(item)
            self.source_items_by_name[source_name] = item

        self._updating_sources = False
        self.on_source_filter_changed(self.source_search_input.text())
        self._refresh_source_status_labels()
        self._refresh_browser_sources_panel()
        self._refresh_catalog_tree()
        self._update_buttons_state()

    def _refresh_source_status_labels(self) -> None:
        total = self.source_list.count()
        visible_count = len(self._visible_source_items())
        checked_count = len(self._checked_source_names())
        selected_count = len(self._selected_source_names())

        self.scene_count_label.setText(f"{self.scene_list.count()} шт.")
        self.source_stats_label.setText(
            f"видно: {visible_count} / всего: {total} / отмечено: {checked_count} / выделено: {selected_count}"
        )
        self._update_buttons_state()

    def on_source_filter_changed(self, text: str) -> None:
        query = (text or "").strip().lower()
        for item in self._all_source_items():
            name = str(item.data(Qt.UserRole) or item.text()).lower()
            item.setHidden(bool(query) and query not in name)
        self._refresh_source_status_labels()
        self._refresh_browser_sources_panel()
        self._refresh_catalog_tree()

    def on_source_item_changed(self, item: QListWidgetItem) -> None:
        if self._loading_scene or self._updating_sources:
            return

        self._save_current_scene_selection()

        if not self._is_online() or not self.obs_connected:
            return

        checked = item.checkState() == Qt.Checked
        ok, message = self._apply_single_source_visibility(item, checked)
        if ok:
            self._set_notice(
                f"{item.data(Qt.UserRole) or item.text()}: {'включён' if checked else 'скрыт'}",
                "success",
                1400,
            )
            return

        previous_state = self._get_source_item_applied_state(item)
        self._updating_sources = True
        self._set_source_item_checked(item, previous_state)
        self._updating_sources = False
        self._save_current_scene_selection()
        self._show_error(
            f"Не удалось переключить источник: {item.data(Qt.UserRole) or item.text()}\n\n{message}",
            popup=False,
        )

    def _refresh_browser_sources_panel(self) -> None:
        scene_name = self._current_scene_name()
        if not scene_name:
            self.browser_sources_box.setPlainText("Сначала загрузи сцены и выбери одну из них.")
            return

        checked_sources = self._checked_source_names()
        selected_sources = self._selected_source_names()
        visible_sources = [item.data(Qt.UserRole) or item.text() for item in self._visible_source_items()]

        lines = [
            f"Текущая сцена: {scene_name}",
            f"Всего источников: {self.source_list.count()}",
            f"Видно после фильтра: {len(visible_sources)}",
            f"Отмечено галочками: {len(checked_sources)}",
            f"Выделено в списке: {len(selected_sources)}",
            "",
        ]

        if checked_sources:
            lines.append("Отмеченные источники:")
            lines.extend(f"• {name}" for name in checked_sources)
        else:
            lines.append("Отмеченных источников нет.")

        self.browser_sources_box.setPlainText("\n".join(lines))

    def _rebuild_scene_scripts_ui(self, scene_name: str) -> None:
        self._updating_scripts = True
        self.script_list.clear()
        self.script_items_by_name.clear()

        scene_name = (scene_name or "").strip()
        self.current_script_scene_label.setText(f"Скрипты сцены: {scene_name or '—'}")

        if not scene_name:
            self.script_stats_label.setText("0 / 0")
            self._refresh_scripts_summary_panel()
            self._updating_scripts = False
            self._update_buttons_state()
            return

        sources = self.obs_inventory.get(scene_name, [])
        saved_enabled = set(self._load_script_scene_selection_from_saved(scene_name))

        for source_name in sources:
            if self._get_item_kind(source_name) != "script":
                continue
            item = QListWidgetItem(self._display_name_with_icons(source_name, "script"))
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            item.setData(Qt.UserRole, source_name)
            checked = source_name in saved_enabled
            self._set_source_item_checked(item, checked)
            self._set_source_item_applied_state(item, checked)
            self.script_list.addItem(item)
            self.script_items_by_name[source_name] = item

        self._updating_scripts = False
        self.on_script_filter_changed(self.script_search_input.text())
        self._refresh_script_status_labels()
        self._refresh_scripts_summary_panel()
        self._refresh_catalog_tree()
        self._update_buttons_state()

    def _refresh_script_status_labels(self) -> None:
        total = self.script_list.count()
        visible_count = len(self._visible_script_items())
        checked_count = len(self._checked_script_names())
        selected_count = len(self._selected_script_names())

        self.script_scene_count_label.setText(f"{self.script_scene_list.count()} шт.")
        self.script_stats_label.setText(
            f"видно: {visible_count} / всего: {total} / отмечено: {checked_count} / выделено: {selected_count}"
        )
        self._update_buttons_state()

    def on_script_filter_changed(self, text: str) -> None:
        query = (text or "").strip().lower()
        for item in self._all_script_items():
            name = str(item.data(Qt.UserRole) or item.text()).lower()
            item.setHidden(bool(query) and query not in name)
        self._refresh_script_status_labels()
        self._refresh_scripts_summary_panel()
        self._refresh_catalog_tree()

    def on_script_item_changed(self, item: QListWidgetItem) -> None:
        if self._loading_script_scene or self._updating_scripts:
            return

        self._save_current_script_selection()

        if not self._is_online() or not self.obs_connected:
            return

        checked = item.checkState() == Qt.Checked
        ok, message = self._apply_single_script_visibility(item, checked)
        if ok:
            self._set_notice(
                f"{item.data(Qt.UserRole) or item.text()}: {'включён' if checked else 'скрыт'}",
                "success",
                1400,
            )
            return

        previous_state = self._get_source_item_applied_state(item)
        self._updating_scripts = True
        self._set_source_item_checked(item, previous_state)
        self._updating_scripts = False
        self._save_current_script_selection()
        self._show_error(
            f"Не удалось переключить скрипт: {item.data(Qt.UserRole) or item.text()}\n\n{message}",
            popup=False,
        )

    def _refresh_scripts_summary_panel(self) -> None:
        scenes = list(self.obs_inventory.keys())
        script_names_all: list[str] = []
        lines = []
        for scene_name in scenes:
            scene_scripts = [name for name in self.obs_inventory.get(scene_name, []) if self._get_item_kind(name) == "script"]
            if scene_scripts:
                lines.append(f"{scene_name} ({len(scene_scripts)}):")
                lines.extend(f"• {name}" for name in scene_scripts)
                lines.append("")
            for name in scene_scripts:
                if name not in script_names_all:
                    script_names_all.append(name)

        current_scene = self._current_script_scene_name()
        header = [
            f"Всего уникальных скриптов: {len(script_names_all)}",
            f"Текущая сцена: {current_scene or '—'}",
            "",
        ]
        if not lines:
            header.append("Скрипты пока не определены. Можно перенести нужные элементы из вкладки «OBS / Источники».")
            self.scripts_summary_box.setPlainText("\n".join(header))
            return
        self.scripts_summary_box.setPlainText("\n".join(header + lines))

    def _sync_current_script_scene_to_obs(self, show_notice: bool = True) -> tuple[int, int, list[str]]:
        scene_name = self._current_script_scene_name()
        success_count = 0
        error_count = 0
        error_lines: list[str] = []

        if not scene_name:
            return success_count, error_count, ["Сцена не выбрана."]

        for item in self._all_script_items():
            source_name = str(item.data(Qt.UserRole) or item.text())
            checked = item.checkState() == Qt.Checked
            ok, message = self._apply_named_item_visibility(scene_name, source_name, checked)
            if ok:
                self._set_source_item_applied_state(item, checked)
                success_count += 1
            else:
                error_count += 1
                error_lines.append(f"{source_name}: {message}")

        self._save_current_script_selection()

        if show_notice:
            if error_count == 0:
                self._show_info(f"Скрипты сцены синхронизированы: {scene_name}. Успешно: {success_count}")
            else:
                self._show_error(
                    f"Скрипты сцены синхронизированы: {scene_name}. Успешно: {success_count}, ошибок: {error_count}.\n\n"
                    + "\n".join(error_lines[:10]),
                    popup=False,
                )

        return success_count, error_count, error_lines

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def refresh_everything(self) -> None:
        online = self._is_online()
        logs_text = self._safe_get_logs()
        if online:
            self._set_status("online", "Статус: online")
        else:
            self._set_status("offline", "Статус: offline")

        self._refresh_provider_statuses()
        self._refresh_obs_connection_state()
        self._update_buttons_state()
        self._set_logs_text(logs_text)

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
        payload = {
            "provider": "donation_alerts",
            "event_type": "donation",
            "title": "Новый донат",
            "donor": self.input_sender.text().strip() or "TarkoFF Supporter",
            "amount": self.input_amount.text().strip() or "250",
            "message": self.input_message.text().strip() or "Тест из GUI",
        }
        ok, msg = self._http_post_json("/api/test", payload)
        if ok:
            self._show_info("Тестовый донат отправлен.")
        else:
            self._show_error(f"Не удалось отправить тестовый донат.\n\n{msg}", popup=False)

    def on_obs_connect_clicked(self) -> None:
        if not self._is_online():
            self._show_warning("Сначала запусти backend.")
            return

        form_data = self._collect_form_settings()
        try:
            self._save_settings_dict(form_data)
        except Exception:
            pass

        password = form_data["obs_password"]
        if not str(password).strip():
            self.obs_connected = False
            self._show_error("Введи пароль OBS в поле Password.", popup=False)
            self._update_obs_status_label(False, "OBS: пароль не указан")
            self._update_buttons_state()
            return

        payload = {
            "host": form_data["obs_host"],
            "port": int(form_data["obs_port"]),
            "password": password,
        }

        ok, data = self._http_post_json_data("/api/obs/connect", payload)
        if ok and isinstance(data, dict) and data.get("ok"):
            self.obs_connected = bool(data.get("connected", True))
            version = data.get("version", {}) or {}
            obs_ver = version.get("obs_version", "unknown")
            current_scene = str(data.get("current_scene", "") or "")
            self.current_obs_scene = current_scene
            status = f"OBS: подключён ({obs_ver})"
            if current_scene:
                status += f" | Сцена: {current_scene}"
            self._update_obs_status_label(True, status)
            self._show_info(data.get("message", "OBS подключён"))
            self._append_obs_log(f"Подключение к OBS: {data.get('message', 'OK')}")
        else:
            self.obs_connected = False
            message = data.get("message", "Не удалось подключиться к OBS") if isinstance(data, dict) else str(data)
            self._update_obs_status_label(False, "OBS: ошибка подключения")
            self._show_error(message, popup=False)
            self._append_obs_log(f"Ошибка подключения к OBS: {message}")

        self._update_buttons_state()

    def on_obs_inventory_clicked(self) -> None:
        if not self._is_online():
            self._show_warning("Сначала запусти backend.")
            return
        if not self.obs_connected:
            self._show_warning("Сначала подключи OBS.")
            return

        ok, data = self._http_get_json_data("/api/obs/scenes-and-sources")
        if not (ok and isinstance(data, dict) and data.get("ok")):
            message = data.get("message", "Не удалось получить список сцен и источников") if isinstance(data, dict) else str(data)
            self._show_error(message, popup=False)
            self._append_obs_log(f"Ошибка загрузки сцен/источников: {message}")
            return

        scenes = [str(scene) for scene in (data.get("scenes", []) or [])]
        sources_by_scene = data.get("sources_by_scene", {}) or {}
        current_scene = str(data.get("current_scene", "") or "").strip()

        self.obs_inventory = {
            scene: [str(x) for x in (sources_by_scene.get(scene, []) or [])]
            for scene in scenes
        }
        self.current_obs_scene = current_scene
        self.current_script_scene = current_scene
        self._ensure_item_kinds_for_inventory()

        self._loading_scene = True
        self.scene_list.clear()
        for scene_name in scenes:
            _scene_item = QListWidgetItem(scene_name)
            _scene_item.setTextAlignment(Qt.AlignCenter)
            self.scene_list.addItem(_scene_item)
        self._loading_scene = False

        self._loading_script_scene = True
        self.script_scene_list.clear()
        for scene_name in scenes:
            _script_scene_item = QListWidgetItem(scene_name)
            _script_scene_item.setTextAlignment(Qt.AlignCenter)
            self.script_scene_list.addItem(_script_scene_item)
        self._loading_script_scene = False

        target_row = 0
        if current_scene and current_scene in scenes:
            target_row = scenes.index(current_scene)

        if scenes:
            self.scene_list.setCurrentRow(target_row)
            self.on_scene_changed(self._current_scene_name())
            self.script_scene_list.setCurrentRow(target_row)
            self.on_script_scene_changed(self._current_script_scene_name())
        else:
            self._rebuild_scene_sources_ui("")
            self._rebuild_scene_scripts_ui("")

        self._refresh_catalog_tree()
        self._show_info("Сцены и источники из OBS обновлены.")
        self._append_obs_log("Сцены и источники загружены из OBS.")
        self._update_buttons_state()

    def on_scene_changed(self, scene_name: str) -> None:
        if self._loading_scene:
            return
        scene_name = str(scene_name or "").strip()
        self._rebuild_scene_sources_ui(scene_name)

    def on_scene_all_on_clicked(self) -> None:
        if not self.source_list.count():
            return
        self._updating_sources = True
        for item in self._all_source_items():
            self._set_source_item_checked(item, True)
        self._updating_sources = False
        self._save_current_scene_selection()
        if self._is_online() and self.obs_connected:
            self._sync_current_scene_to_obs(show_notice=True)

    def on_scene_all_off_clicked(self) -> None:
        if not self.source_list.count():
            return
        self._updating_sources = True
        for item in self._all_source_items():
            self._set_source_item_checked(item, False)
        self._updating_sources = False
        self._save_current_scene_selection()
        if self._is_online() and self.obs_connected:
            self._sync_current_scene_to_obs(show_notice=True)

    def _set_selected_sources_visible(self, visible: bool) -> None:
        if not self._is_online():
            self._show_warning("Сначала запусти backend.")
            return
        if not self.obs_connected:
            self._show_warning("OBS не подключён. Нажми «Подключить OBS».")
            return

        scene_name = self._current_scene_name()
        if not scene_name:
            self._show_warning("Сцена не выбрана.")
            return

        selected_sources = self._selected_source_names()
        if not selected_sources:
            self._show_warning("Сначала выдели источники в списке справа.")
            return

        success_count = 0
        error_count = 0
        action_name = "Показать" if visible else "Скрыть"
        endpoint = "/api/obs/show-source" if visible else "/api/obs/hide-source"

        for source_name in selected_sources:
            ok, data = self._http_post_json_data(endpoint, {"scene_name": scene_name, "source_name": source_name})
            if ok and isinstance(data, dict) and data.get("ok"):
                success_count += 1
                self._append_obs_log(f"[{scene_name}] {action_name}: {source_name}")
            else:
                error_count += 1
                message = data.get("message", "ошибка") if isinstance(data, dict) else str(data)
                self._append_obs_log(f"[{scene_name}] Ошибка {action_name.lower()} {source_name}: {message}")

        if success_count:
            self._updating_sources = True
            for item in self._all_source_items():
                source_name = str(item.data(Qt.UserRole) or item.text())
                if source_name in selected_sources:
                    self._set_source_item_checked(item, visible)
                    self._set_source_item_applied_state(item, visible)
            self._updating_sources = False
            self._save_current_scene_selection()

        self._show_info(
            f"{action_name} выбранных завершён. Успешно: {success_count}, ошибок: {error_count}"
        )

    def on_scene_show_selected_clicked(self) -> None:
        self._set_selected_sources_visible(True)

    def on_scene_hide_selected_clicked(self) -> None:
        self._set_selected_sources_visible(False)

    def on_apply_scene_clicked(self) -> None:
        if not self._is_online():
            self._show_warning("Сначала запусти backend.")
            return
        if not self.obs_connected:
            self._show_warning("OBS не подключён. Нажми «Подключить OBS».")
            return

        scene_name = self._current_scene_name()
        if not scene_name:
            self._show_warning("Сцена не выбрана.")
            return

        self._sync_current_scene_to_obs(show_notice=True)

    def on_scene_refresh_checked_clicked(self) -> None:
        if not self._is_online():
            self._show_warning("Сначала запусти backend.")
            return
        if not self.obs_connected:
            self._show_warning("OBS не подключён. Нажми «Подключить OBS».")
            return

        checked_sources = self._checked_source_names()
        if not checked_sources:
            self._show_warning("Нет отмеченных источников.")
            return

        success_count = 0
        error_count = 0
        for source_name in checked_sources:
            ok, data = self._http_post_json_data("/api/obs/refresh-browser-source", {"source_name": source_name})
            if ok and isinstance(data, dict) and data.get("ok"):
                success_count += 1
                self._append_obs_log(f"Обновить страницу: {source_name}")
            else:
                error_count += 1
                message = data.get("message", "ошибка") if isinstance(data, dict) else str(data)
                self._append_obs_log(f"Ошибка обновления страницы {source_name}: {message}")

        self._show_info(f"Обновление отмеченных источников завершено. Успешно: {success_count}, ошибок: {error_count}")

    def on_refresh_all_browser_sources_clicked(self) -> None:
        if not self._is_online():
            self._show_warning("Сначала запусти backend.")
            return
        if not self.obs_connected:
            self._show_warning("OBS не подключён. Нажми «Подключить OBS».")
            return

        all_sources: list[str] = []
        for scene_sources in self.obs_inventory.values():
            for source_name in scene_sources:
                if source_name not in all_sources:
                    all_sources.append(source_name)

        if not all_sources:
            self._show_warning("Сначала загрузи сцены и источники.")
            return

        success_count = 0
        error_count = 0
        for source_name in all_sources:
            ok, data = self._http_post_json_data("/api/obs/refresh-browser-source", {"source_name": source_name})
            if ok and isinstance(data, dict) and data.get("ok"):
                success_count += 1
                self._append_obs_log(f"Обновить страницу: {source_name}")
            else:
                error_count += 1

        self._show_info(f"Массовое обновление страниц завершено. Успешно: {success_count}, ошибок: {error_count}")

    def on_script_scene_changed(self, scene_name: str) -> None:
        if self._loading_script_scene:
            return
        scene_name = str(scene_name or "").strip()
        self._rebuild_scene_scripts_ui(scene_name)

    def _set_selected_script_items_visible(self, visible: bool) -> None:
        if not self._is_online():
            self._show_warning("Сначала запусти backend.")
            return
        if not self.obs_connected:
            self._show_warning("OBS не подключён. Нажми «Подключить OBS».")
            return

        scene_name = self._current_script_scene_name()
        if not scene_name:
            self._show_warning("Сцена не выбрана.")
            return

        selected_sources = self._selected_script_names()
        if not selected_sources:
            self._show_warning("Сначала выдели скрипты в списке справа.")
            return

        success_count = 0
        error_count = 0
        action_name = "Показать" if visible else "Скрыть"

        for source_name in selected_sources:
            ok, message = self._apply_named_item_visibility(scene_name, source_name, visible)
            if ok:
                success_count += 1
            else:
                error_count += 1
                self._append_obs_log(f"[{scene_name}] Ошибка {action_name.lower()} {source_name}: {message}")

        if success_count:
            self._updating_scripts = True
            for item in self._all_script_items():
                source_name = str(item.data(Qt.UserRole) or item.text())
                if source_name in selected_sources:
                    self._set_source_item_checked(item, visible)
                    self._set_source_item_applied_state(item, visible)
            self._updating_scripts = False
            self._save_current_script_selection()

        self._show_info(
            f"{action_name} выбранных скриптов завершён. Успешно: {success_count}, ошибок: {error_count}"
        )

    def on_script_show_selected_clicked(self) -> None:
        self._set_selected_script_items_visible(True)

    def on_script_hide_selected_clicked(self) -> None:
        self._set_selected_script_items_visible(False)

    def on_apply_script_scene_clicked(self) -> None:
        if not self._is_online():
            self._show_warning("Сначала запусти backend.")
            return
        if not self.obs_connected:
            self._show_warning("OBS не подключён. Нажми «Подключить OBS».")
            return

        scene_name = self._current_script_scene_name()
        if not scene_name:
            self._show_warning("Сцена не выбрана.")
            return

        self._sync_current_script_scene_to_obs(show_notice=True)

    def on_script_all_on_clicked(self) -> None:
        if not self.script_list.count():
            return
        self._updating_scripts = True
        for item in self._all_script_items():
            self._set_source_item_checked(item, True)
        self._updating_scripts = False
        self._save_current_script_selection()
        if self._is_online() and self.obs_connected:
            self._sync_current_script_scene_to_obs(show_notice=True)

    def on_script_all_off_clicked(self) -> None:
        if not self.script_list.count():
            return
        self._updating_scripts = True
        for item in self._all_script_items():
            self._set_source_item_checked(item, False)
        self._updating_scripts = False
        self._save_current_script_selection()
        if self._is_online() and self.obs_connected:
            self._sync_current_script_scene_to_obs(show_notice=True)

    def on_script_refresh_checked_clicked(self) -> None:
        if not self._is_online():
            self._show_warning("Сначала запусти backend.")
            return
        if not self.obs_connected:
            self._show_warning("OBS не подключён. Нажми «Подключить OBS».")
            return

        checked_sources = self._checked_script_names()
        if not checked_sources:
            self._show_warning("Нет отмеченных скриптов.")
            return

        success_count = 0
        error_count = 0
        for source_name in checked_sources:
            ok, data = self._http_post_json_data("/api/obs/refresh-browser-source", {"source_name": source_name})
            if ok and isinstance(data, dict) and data.get("ok"):
                success_count += 1
                self._append_obs_log(f"Обновить страницу: {source_name}")
            else:
                error_count += 1
                message = data.get("message", "ошибка") if isinstance(data, dict) else str(data)
                self._append_obs_log(f"Ошибка обновления страницы {source_name}: {message}")

        self._show_info(f"Обновление отмеченных скриптов завершено. Успешно: {success_count}, ошибок: {error_count}")

    def _move_items_to_kind(self, names: list[str], kind: str) -> None:
        if not names:
            return
        for name in names:
            self._set_item_kind(name, kind)

        current_source_scene = self._current_scene_name()
        current_script_scene = self._current_script_scene_name()
        self._rebuild_scene_sources_ui(current_source_scene)
        self._rebuild_scene_scripts_ui(current_script_scene)
        self._refresh_scripts_summary_panel()
        self._refresh_catalog_tree()
        self._set_notice(
            f"Перенесено: {len(names)} шт. → {'Скрипты' if kind == 'script' else 'Источники'}",
            "success",
            2000,
        )

    def on_move_selected_sources_to_scripts_clicked(self) -> None:
        names = self._selected_source_names()
        if not names:
            self._show_warning("Сначала выдели источники, которые нужно перенести в «Скрипты».")
            return
        self._move_items_to_kind(names, "script")

    def on_move_selected_scripts_to_sources_clicked(self) -> None:
        names = self._selected_script_names()
        if not names:
            self._show_warning("Сначала выдели скрипты, которые нужно вернуть в «Источники».")
            return
        self._move_items_to_kind(names, "source")

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

    def closeEvent(self, event) -> None:  # type: ignore[override]
        try:
            if hasattr(self, "refresh_timer") and self.refresh_timer is not None:
                self.refresh_timer.stop()
            if hasattr(self, "notice_timer") and self.notice_timer is not None:
                self.notice_timer.stop()
        except Exception:
            pass
        super().closeEvent(event)
