"""Settings panel — provider management, model A/B, translation parameters."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.config import ConfigManager
from core.models import Provider, ModelPricing


_STYLE_OPTIONS = ["дословный", "литературный", "адаптированный"]

_MODEL_PRESETS = [
    "gpt-4o", "gpt-4o-mini", "gpt-4", "gpt-3.5-turbo",
    "claude-3-5-sonnet-20241022", "claude-3-haiku-20240307",
    "deepseek-chat", "deepseek-reasoner",
    "llama3.1", "llama3.2", "mistral", "mixtral",
    "gemini/gemini-1.5-pro", "gemini/gemini-1.5-flash",
]


class SettingsPanel(QWidget):
    """Translation settings: providers, model A/B, temperature, style, etc.

    Emits:
        settings_changed():  whenever any setting is modified.
        comparison_toggled(enabled):  when the comparison checkbox changes.
    """

    settings_changed = pyqtSignal()
    comparison_toggled = pyqtSignal(bool)

    def __init__(self, config_manager: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = config_manager
        self._providers: list[Provider] = []
        self._suppress_signals = False

        self._build_ui()
        self._load_settings()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        # -- Provider management ----------------------------------------
        prov_group = QGroupBox("Поставщики API")
        prov_layout = QVBoxLayout(prov_group)

        self._provider_list = QListWidget()
        self._provider_list.currentRowChanged.connect(self._on_provider_selected)
        prov_layout.addWidget(self._provider_list)

        prov_btn_row = QHBoxLayout()
        self._add_prov_btn = QPushButton("➕ Добавить")
        self._add_prov_btn.clicked.connect(self._on_add_provider)
        self._edit_prov_btn = QPushButton("✏️ Редактировать")
        self._edit_prov_btn.clicked.connect(self._on_edit_provider)
        self._edit_prov_btn.setEnabled(False)
        self._del_prov_btn = QPushButton("🗑️ Удалить")
        self._del_prov_btn.clicked.connect(self._on_delete_provider)
        self._del_prov_btn.setEnabled(False)

        prov_btn_row.addWidget(self._add_prov_btn)
        prov_btn_row.addWidget(self._edit_prov_btn)
        prov_btn_row.addWidget(self._del_prov_btn)
        prov_btn_row.addStretch()
        prov_layout.addLayout(prov_btn_row)

        outer.addWidget(prov_group)

        # -- Model selection --------------------------------------------
        model_group = QGroupBox("Модели для перевода")
        model_layout = QFormLayout(model_group)

        self._model_a_combo = QComboBox()
        self._model_a_combo.setEditable(True)
        self._model_a_combo.setPlaceholderText("Выберите или введите модель...")
        self._model_a_combo.currentTextChanged.connect(self._on_setting_changed)

        self._compare_check = QCheckBox("Сравнить с другой моделью")
        self._compare_check.toggled.connect(self._on_comparison_toggled)

        self._model_b_combo = QComboBox()
        self._model_b_combo.setEditable(True)
        self._model_b_combo.setPlaceholderText("Выберите или введите модель...")
        self._model_b_combo.setVisible(False)
        self._model_b_combo.currentTextChanged.connect(self._on_setting_changed)

        model_layout.addRow("Model A:", self._model_a_combo)
        model_layout.addRow("", self._compare_check)
        model_layout.addRow("Model B:", self._model_b_combo)

        outer.addWidget(model_group)

        # -- Translation parameters -------------------------------------
        param_group = QGroupBox("Параметры перевода")
        param_layout = QFormLayout(param_group)

        self._temp_spin = QDoubleSpinBox()
        self._temp_spin.setRange(0.0, 1.0)
        self._temp_spin.setSingleStep(0.05)
        self._temp_spin.setDecimals(2)
        self._temp_spin.valueChanged.connect(self._on_setting_changed)

        self._top_p_spin = QDoubleSpinBox()
        self._top_p_spin.setRange(0.0, 1.0)
        self._top_p_spin.setSingleStep(0.05)
        self._top_p_spin.setDecimals(2)
        self._top_p_spin.valueChanged.connect(self._on_setting_changed)

        self._max_tokens_spin = QSpinBox()
        self._max_tokens_spin.setRange(64, 128000)
        self._max_tokens_spin.setSingleStep(256)
        self._max_tokens_spin.valueChanged.connect(self._on_setting_changed)

        self._style_combo = QComboBox()
        self._style_combo.addItems(_STYLE_OPTIONS)
        self._style_combo.currentTextChanged.connect(self._on_setting_changed)

        param_layout.addRow("Temperature:", self._temp_spin)
        param_layout.addRow("Top-p:", self._top_p_spin)
        param_layout.addRow("Max tokens:", self._max_tokens_spin)
        param_layout.addRow("Стиль:", self._style_combo)

        outer.addWidget(param_group)
        outer.addStretch()

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def _load_settings(self) -> None:
        self._suppress_signals = True

        # Providers
        self._providers = self._cfg.load_providers()
        self._refresh_provider_list()

        # App config
        cfg = self._cfg.load_app_config()
        self._temp_spin.setValue(float(cfg.get("temperature", 0.3)))
        self._top_p_spin.setValue(float(cfg.get("top_p", 0.9)))
        self._max_tokens_spin.setValue(int(cfg.get("max_tokens", 4096)))
        self._style_combo.setCurrentText(cfg.get("style", "литературный"))

        # Model combos
        self._populate_model_combos()
        last_a = cfg.get("last_model_a", "")
        last_b = cfg.get("last_model_b", "")
        compare = cfg.get("comparison_enabled", False)
        if last_a:
            self._model_a_combo.setCurrentText(last_a)
        if last_b:
            self._model_b_combo.setCurrentText(last_b)
        self._compare_check.setChecked(compare)
        self._model_b_combo.setVisible(compare)

        self._suppress_signals = False

    def save_settings(self) -> None:
        cfg = self._cfg.load_app_config()
        cfg["temperature"] = self._temp_spin.value()
        cfg["top_p"] = self._top_p_spin.value()
        cfg["max_tokens"] = self._max_tokens_spin.value()
        cfg["style"] = self._style_combo.currentText()
        cfg["last_model_a"] = self._model_a_combo.currentText()
        cfg["last_model_b"] = self._model_b_combo.currentText()
        cfg["comparison_enabled"] = self._compare_check.isChecked()
        if self._provider_list.currentRow() >= 0:
            selected = self._providers[self._provider_list.currentRow()]
            cfg["last_provider_id"] = selected.id
        self._cfg.save_app_config(cfg)

    # ------------------------------------------------------------------
    # Provider list helpers
    # ------------------------------------------------------------------

    def _refresh_provider_list(self) -> None:
        self._provider_list.blockSignals(True)
        self._provider_list.clear()
        for p in self._providers:
            item = QListWidgetItem(f"{p.name}  ({p.default_model})")
            item.setData(1, p.id)  # store provider id
            self._provider_list.addItem(item)
        self._provider_list.blockSignals(False)

    def _populate_model_combos(self) -> None:
        models: list[str] = list(_MODEL_PRESETS)
        for p in self._providers:
            for model_name in p.models:
                full = f"{p.id}/{model_name}"
                if full not in models:
                    models.append(full)
            if p.default_model:
                full = f"{p.id}/{p.default_model}"
                if full not in models:
                    models.append(full)

        self._model_a_combo.blockSignals(True)
        self._model_b_combo.blockSignals(True)
        current_a = self._model_a_combo.currentText()
        current_b = self._model_b_combo.currentText()

        self._model_a_combo.clear()
        self._model_b_combo.clear()
        self._model_a_combo.addItems(models)
        self._model_b_combo.addItems(models)

        if current_a:
            self._model_a_combo.setCurrentText(current_a)
        if current_b:
            self._model_b_combo.setCurrentText(current_b)

        self._model_a_combo.blockSignals(False)
        self._model_b_combo.blockSignals(False)

    # ------------------------------------------------------------------
    # Provider CRUD dialogs
    # ------------------------------------------------------------------

    def _on_add_provider(self) -> None:
        dialog = _ProviderDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            provider = dialog.get_provider()
            self._providers = self._cfg.add_provider(provider)
            self._refresh_provider_list()
            self._populate_model_combos()
            self._emit_changed()

    def _on_edit_provider(self) -> None:
        row = self._provider_list.currentRow()
        if row < 0 or row >= len(self._providers):
            return
        provider = self._providers[row]
        dialog = _ProviderDialog(self, provider)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated = dialog.get_provider()
            self._providers = self._cfg.update_provider(updated)
            self._refresh_provider_list()
            self._populate_model_combos()
            self._emit_changed()

    def _on_delete_provider(self) -> None:
        row = self._provider_list.currentRow()
        if row < 0 or row >= len(self._providers):
            return
        provider = self._providers[row]
        answer = QMessageBox.question(
            self,
            "Удалить провайдера",
            f'Удалить «{provider.name}»?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._providers = self._cfg.remove_provider(provider.id)
        self._refresh_provider_list()
        self._populate_model_combos()
        self._emit_changed()

    def _on_provider_selected(self, row: int) -> None:
        has_selection = row >= 0 and row < len(self._providers)
        self._edit_prov_btn.setEnabled(has_selection)
        self._del_prov_btn.setEnabled(has_selection)

    # ------------------------------------------------------------------
    # Comparison toggle
    # ------------------------------------------------------------------

    def _on_comparison_toggled(self, enabled: bool) -> None:
        self._model_b_combo.setVisible(enabled)
        self.comparison_toggled.emit(enabled)
        self._emit_changed()

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _on_setting_changed(self) -> None:
        self._emit_changed()

    def _emit_changed(self) -> None:
        if not self._suppress_signals:
            self.save_settings()
            self.settings_changed.emit()

    # ------------------------------------------------------------------
    # Public getters
    # ------------------------------------------------------------------

    def get_model_a(self) -> str:
        return self._model_a_combo.currentText().strip()

    def get_model_b(self) -> str:
        return self._model_b_combo.currentText().strip()

    def is_comparison_enabled(self) -> bool:
        return self._compare_check.isChecked()

    def get_temperature(self) -> float:
        return self._temp_spin.value()

    def get_top_p(self) -> float:
        return self._top_p_spin.value()

    def get_max_tokens(self) -> int:
        return self._max_tokens_spin.value()

    def get_style(self) -> str:
        return self._style_combo.currentText()


# ======================================================================
# Provider add/edit dialog
# ======================================================================


class _ProviderDialog(QDialog):
    """Simple dialog for adding/editing a provider."""

    def __init__(
        self,
        parent: QWidget | None = None,
        provider: Provider | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Провайдер" if provider is None else "Редактировать провайдера")
        self.setMinimumWidth(420)
        self._provider = provider

        self._name_edit = QLineEdit()
        self._url_edit = QLineEdit()
        self._key_edit = QLineEdit()
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.addItems([
            "gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo",
            "claude-3-5-sonnet-20241022", "deepseek-chat",
            "llama3.1", "llama3.2", "mistral",
        ])

        if provider is not None:
            self._name_edit.setText(provider.name)
            self._url_edit.setText(provider.base_url)
            self._key_edit.setText(provider.api_key or "")
            self._model_combo.setCurrentText(provider.default_model)

        layout = QVBoxLayout()
        form = QFormLayout()
        form.addRow("Название:", self._name_edit)
        form.addRow("API Base URL:", self._url_edit)
        form.addRow("API Key:", self._key_edit)
        form.addRow("Модель:", self._model_combo)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        self._ok_btn = QPushButton("OK")
        self._ok_btn.clicked.connect(self._on_ok)
        self._cancel_btn = QPushButton("Отмена")
        self._cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(self._ok_btn)
        btn_row.addWidget(self._cancel_btn)
        layout.addLayout(btn_row)

        self.setLayout(layout)

    def _on_ok(self) -> None:
        if not self._name_edit.text().strip():
            QMessageBox.warning(self, "Ошибка", "Название обязательно")
            return
        if not self._url_edit.text().strip():
            QMessageBox.warning(self, "Ошибка", "URL обязателен")
            return
        self.accept()

    def get_provider(self) -> Provider:
        _id = self._provider.id if self._provider else self._name_edit.text().strip().lower().replace(" ", "_")
        model_name = self._model_combo.currentText().strip() or "gpt-4o"
        return Provider(
            id=_id,
            name=self._name_edit.text().strip(),
            base_url=self._url_edit.text().strip(),
            api_key=self._key_edit.text().strip() or None,
            models={model_name: ModelPricing(input_cost_per_1k=0, output_cost_per_1k=0)},
            default_model=model_name,
        )
