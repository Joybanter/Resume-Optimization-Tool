"""设置界面（PRD 3.2.7 / 5.4）。

包含：
- API 配置：API Key（密码模式）、模型切换（PRD F10）、Base URL、测试连接、保存
- 导出设置：默认保存目录、导出格式（Word / PDF）
- DeepSeek 注册指引
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from .. import config
from ..core.llm_client import LLMClient, LLMError


class TestConnectionWorker(QThread):
    """测试连接后台线程（避免阻塞设置界面）。"""

    finished_ok = Signal(bool, str)

    def __init__(self, api_key: str, base_url: str, model: str, parent=None):
        super().__init__(parent)
        self._api_key = api_key
        self._base_url = base_url
        self._model = model

    def run(self) -> None:
        try:
            client = LLMClient(self._api_key, self._base_url, self._model)
            ok, message = client.test_connection()
            self.finished_ok.emit(ok, message)
        except LLMError as exc:
            self.finished_ok.emit(False, str(exc))
        except Exception as exc:
            self.finished_ok.emit(False, f"测试失败：{exc}")


class SettingsDialog(QDialog):
    """设置对话框。"""

    settingsSaved = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(560)
        self._test_worker: TestConnectionWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        # ---- API 配置 ----
        api_box = QGroupBox("API 配置")
        api_grid = QGridLayout(api_box)
        api_grid.setContentsMargins(14, 14, 14, 14)
        api_grid.setHorizontalSpacing(10)
        api_grid.setVerticalSpacing(10)

        api_grid.addWidget(QLabel("API Key："), 0, 0)
        key_row = QHBoxLayout()
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-…（DeepSeek API Key）")
        self.show_key_button = QPushButton("显示")
        self.show_key_button.setObjectName("secondaryButton")
        self.show_key_button.setCheckable(True)
        self.show_key_button.toggled.connect(self._toggle_key_visible)
        key_row.addWidget(self.api_key_edit, stretch=1)
        key_row.addWidget(self.show_key_button)
        api_grid.addLayout(key_row, 0, 1)

        api_grid.addWidget(QLabel("模型："), 1, 0)
        self.model_combo = QComboBox()
        for model_id, display in config.AVAILABLE_MODELS.items():
            self.model_combo.addItem(display, model_id)
        api_grid.addWidget(self.model_combo, 1, 1)

        api_grid.addWidget(QLabel("API 地址："), 2, 0)
        self.base_url_edit = QLineEdit()
        api_grid.addWidget(self.base_url_edit, 2, 1)

        actions_row = QHBoxLayout()
        self.test_button = QPushButton("测试连接")
        self.test_button.setObjectName("secondaryButton")
        self.test_button.clicked.connect(self.on_test_connection)
        self.save_button = QPushButton("保存")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self.on_save)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        actions_row.addWidget(self.test_button)
        actions_row.addWidget(self.save_button)
        actions_row.addWidget(self.status_label, stretch=1)
        api_grid.addLayout(actions_row, 3, 0, 1, 2)

        layout.addWidget(api_box)

        # ---- 导出设置 ----
        export_box = QGroupBox("导出设置")
        export_grid = QGridLayout(export_box)
        export_grid.setContentsMargins(14, 14, 14, 14)
        export_grid.setHorizontalSpacing(10)
        export_grid.setVerticalSpacing(10)

        export_grid.addWidget(QLabel("默认保存目录："), 0, 0)
        dir_row = QHBoxLayout()
        self.export_dir_edit = QLineEdit()
        self.browse_button = QPushButton("浏览…")
        self.browse_button.setObjectName("secondaryButton")
        self.browse_button.clicked.connect(self.on_browse_dir)
        dir_row.addWidget(self.export_dir_edit, stretch=1)
        dir_row.addWidget(self.browse_button)
        export_grid.addLayout(dir_row, 0, 1)

        export_grid.addWidget(QLabel("导出格式："), 1, 0)
        format_row = QHBoxLayout()
        self.export_word_check = QCheckBox("Word (.docx)")
        self.export_pdf_check = QCheckBox("PDF（需本机安装 Word/WPS）")
        format_row.addWidget(self.export_word_check)
        format_row.addWidget(self.export_pdf_check)
        format_row.addStretch(1)
        export_grid.addLayout(format_row, 1, 1)

        layout.addWidget(export_box)

        # ---- 注册指引（PRD 5.4）----
        guide_box = QGroupBox("注册 DeepSeek API")
        guide_layout = QVBoxLayout(guide_box)
        guide_layout.setContentsMargins(14, 12, 14, 12)
        guide_1 = QLabel(
            '1. 注册账号：<a href="https://platform.deepseek.com">'
            "https://platform.deepseek.com</a>"
        )
        guide_2 = QLabel(
            '2. 创建 API Key：<a href="https://platform.deepseek.com/api_keys">'
            "https://platform.deepseek.com/api_keys</a>"
        )
        guide_3 = QLabel("3. 复制 Key 填入上方输入框，点击“测试连接”验证后保存")
        for label in (guide_1, guide_2, guide_3):
            label.setOpenExternalLinks(True)
            label.setTextFormat(Qt.TextFormat.RichText)
            guide_layout.addWidget(label)
        layout.addWidget(guide_box)

        layout.addStretch(1)

        # ---- 关闭按钮 ----
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        self.close_button = QPushButton("关闭")
        self.close_button.setObjectName("secondaryButton")
        self.close_button.clicked.connect(self.reject)
        close_row.addWidget(self.close_button)
        layout.addLayout(close_row)

        self._load_settings()

    # ==================================================================
    # 加载 / 保存
    # ==================================================================

    def _load_settings(self) -> None:
        settings = config.get_settings()
        api_key = config.load_api_key()
        if api_key:
            self.api_key_edit.setText(api_key)
            self.api_key_edit.setPlaceholderText("（已配置，输入新值可替换）")
        index = self.model_combo.findData(settings["model"])
        if index >= 0:
            self.model_combo.setCurrentIndex(index)
        self.base_url_edit.setText(settings["base_url"])
        self.export_dir_edit.setText(settings["export_dir"])
        self.export_word_check.setChecked(bool(settings.get("export_word", True)))
        self.export_pdf_check.setChecked(bool(settings.get("export_pdf", True)))

    def _toggle_key_visible(self, checked: bool) -> None:
        self.api_key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )
        self.show_key_button.setText("隐藏" if checked else "显示")

    def on_browse_dir(self) -> None:
        current = self.export_dir_edit.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "选择默认保存目录", current)
        if path:
            self.export_dir_edit.setText(path)

    def _collect(self) -> dict:
        return {
            "model": self.model_combo.currentData() or config.DEFAULT_MODEL,
            "base_url": self.base_url_edit.text().strip() or config.DEFAULT_BASE_URL,
            "export_dir": self.export_dir_edit.text().strip()
            or config.default_export_dir(),
            "export_word": self.export_word_check.isChecked(),
            "export_pdf": self.export_pdf_check.isChecked(),
        }

    def on_save(self) -> None:
        api_key = self.api_key_edit.text().strip()
        try:
            if api_key:
                config.save_api_key(api_key)
            config.update_settings(**self._collect())
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", f"保存设置时出错：{exc}")
            return
        self.status_label.setText("✓ 已保存")
        self.settingsSaved.emit()
        self.accept()

    # ==================================================================
    # 测试连接
    # ==================================================================

    def on_test_connection(self) -> None:
        api_key = self.api_key_edit.text().strip()
        if not api_key:
            api_key = config.load_api_key()
            if not api_key:
                self.status_label.setText("✗ 请先填写 API Key")
                return
        if self._test_worker and self._test_worker.isRunning():
            return
        base_url = self.base_url_edit.text().strip() or config.DEFAULT_BASE_URL
        model = self.model_combo.currentData() or config.DEFAULT_MODEL
        self.test_button.setEnabled(False)
        self.status_label.setText("正在测试连接…")
        self._test_worker = TestConnectionWorker(api_key, base_url, model)
        self._test_worker.finished_ok.connect(self._on_test_done)
        self._test_worker.start()

    def _on_test_done(self, ok: bool, message: str) -> None:
        self.test_button.setEnabled(True)
        if ok:
            self.status_label.setText(f"✓ 连接正常（{message}）")
        else:
            self.status_label.setText(f"✗ {message}")