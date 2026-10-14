"""主界面（PRD 5.1）。

布局：
┌─────────────────────────────────────────────┐
│ 标题                        [设置] [历史记录] │
│ ┌────────────┐  ┌─────────────────────────┐ │
│ │ ① 上传简历  │  │ ② 岗位名称 + JD 粘贴     │ │
│ └────────────┘  └─────────────────────────┘ │
│ ③ 改写尺度选择（保守/中度/深度）              │
│            [ 开始优化简历 ]                  │
│ 状态栏：状态 | 模型 | API                    │
└─────────────────────────────────────────────┘

优化任务在 QThread 中执行，避免阻塞 UI；
完成后弹出对比预览窗口（PRD 5.3）。
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .. import config
from ..core.docx_parser import ParsedDocument, ResumeParseError, estimate_tokens, parse_docx
from ..core.history_db import HistoryDB
from ..core.llm_client import LLMClient, LLMError
from ..core.resume_optimizer import (
    OptimizationCanceled,
    OptimizeRequest,
    ResumeOptimizer,
)
from ..core.docx_filler import fill_resume
from ..core.pdf_converter import PdfConversionError, convert_docx_to_pdf
from .components.clickable_label import ClickableLabel
from .components.drop_zone import DropZone
from .components.progress_bar import OptimizationProgressDialog
from .history_window import HistoryWindow
from .onboarding_dialog import OnboardingDialog
from .preview_window import PreviewWindow
from .settings_dialog import SettingsDialog

logger = logging.getLogger(__name__)

#: JD 字数边界（PRD 3.2.2 / 8）
JD_MIN_HINT_CHARS = 100
JD_MAX_CHARS = 10000


class OptimizeWorker(QThread):
    """后台优化任务线程。"""

    progress = Signal(int, str, str)  # percent, stage, message
    finished_ok = Signal(object)  # OptimizeResult
    canceled = Signal()
    failed = Signal(str)

    def __init__(self, request: OptimizeRequest, api_key: str, base_url: str, model: str, parent=None):
        super().__init__(parent)
        self._request = request
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._cancel_flag = False

    def request_cancel(self) -> None:
        self._cancel_flag = True

    def run(self) -> None:  # QThread 入口
        optimizer = ResumeOptimizer(self._api_key, self._base_url, self._model)
        try:
            result = optimizer.run(
                self._request,
                progress_cb=lambda p, s, m: self.progress.emit(p, s, m),
                cancel_check=lambda: self._cancel_flag,
            )
            self.finished_ok.emit(result)
        except OptimizationCanceled:
            self.canceled.emit()
        except ResumeParseError as exc:
            self.failed.emit(str(exc))
        except LLMError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # 兜底：不让线程静默崩溃
            logger.exception("优化任务异常")
            self.failed.emit(f"发生未预期的错误：{exc}")


class JdCleanWorker(QThread):
    """"粘贴并清理"后台任务（PRD 3.2.2）。"""

    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, api_key: str, base_url: str, model: str, jd_text: str, parent=None):
        super().__init__(parent)
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._jd_text = jd_text

    def run(self) -> None:
        try:
            client = LLMClient(self._api_key, self._base_url, self._model)
            cleaned = client.clean_jd(self._jd_text)
            self.finished_ok.emit(cleaned)
        except LLMError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            logger.exception("JD 清理任务异常")
            self.failed.emit(f"清理失败：{exc}")


class MainWindow(QMainWindow):
    """简历优化工具主窗口。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("简历优化工具 v1.0")
        self.resize(1020, 720)
        self.setMinimumSize(880, 640)

        # ---- 运行状态 ----
        self.parsed_doc: ParsedDocument | None = None
        self.resume_path: str = ""
        self._optimize_worker: OptimizeWorker | None = None
        self._jd_clean_worker: JdCleanWorker | None = None
        self._progress_dialog: OptimizationProgressDialog | None = None
        self._last_result = None  # 最近一次优化结果（重新生成用）

        # ---- 彩蛋：标题连点计数（3 秒内无点击自动重置）----
        self._title_click_count = 0
        self._title_reset_timer = QTimer(self)
        self._title_reset_timer.setSingleShot(True)
        self._title_reset_timer.setInterval(3000)
        self._title_reset_timer.timeout.connect(self._reset_title_clicks)
        self._easter_egg_window = None

        self._build_ui()
        self.refresh_status_bar()

    # ==================================================================
    # UI 构建
    # ==================================================================

    def _build_ui(self) -> None:
        central = QWidget()
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(24, 18, 24, 12)
        root_layout.setSpacing(14)

        # ---- 顶部标题行 ----
        top_row = QHBoxLayout()
        # 左上角问号：随时重新唤起新手指引
        self.help_button = QPushButton("?")
        self.help_button.setObjectName("helpButton")
        self.help_button.setFixedSize(30, 30)
        self.help_button.setToolTip("不会使用？点这里")
        self.help_button.clicked.connect(self.open_onboarding)
        # 标题（隐藏彩蛋入口：连点 5 次）
        self.title_label = ClickableLabel("简历优化工具")
        self.title_label.setObjectName("appTitle")
        self.title_label.clicked.connect(self._on_title_clicked)
        subtitle = QLabel("上传简历 · 粘贴 JD · 一键生成适配岗位的定制简历")
        subtitle.setObjectName("appSubtitle")
        self.settings_button = QPushButton("设置")
        self.settings_button.setObjectName("secondaryButton")
        self.settings_button.clicked.connect(self.open_settings)
        self.history_button = QPushButton("历史记录")
        self.history_button.setObjectName("secondaryButton")
        self.history_button.clicked.connect(self.open_history)
        # 与标题文字垂直居中对齐（此前 AlignTop 导致错位）
        top_row.addWidget(self.help_button, 0, Qt.AlignmentFlag.AlignVCenter)
        top_row.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignVCenter)
        top_row.addWidget(subtitle, stretch=1)
        top_row.addWidget(self.settings_button)
        top_row.addWidget(self.history_button)
        root_layout.addLayout(top_row)

        # ---- 左右两栏：上传简历 / JD 粘贴 ----
        columns = QHBoxLayout()
        columns.setSpacing(16)

        # 左：上传简历
        upload_box = QGroupBox("① 上传简历")
        upload_layout = QVBoxLayout(upload_box)
        upload_layout.setContentsMargins(14, 18, 14, 14)
        self.drop_zone = DropZone()
        self.drop_zone.fileDropped.connect(self.on_file_selected)
        upload_layout.addWidget(self.drop_zone)
        columns.addWidget(upload_box, stretch=5)

        # 右：岗位名称 + JD
        jd_box = QGroupBox("② 粘贴目标岗位要求（JD）")
        jd_layout = QVBoxLayout(jd_box)
        jd_layout.setContentsMargins(14, 18, 14, 14)
        jd_layout.setSpacing(8)

        jd_title_row = QHBoxLayout()
        jd_title_label = QLabel("岗位名称：")
        self.jd_title_edit = QLineEdit()
        self.jd_title_edit.setPlaceholderText("例如：品类运营（用于结果文件命名）")
        self.jd_title_edit.setMaximumWidth(320)
        jd_title_row.addWidget(jd_title_label)
        jd_title_row.addWidget(self.jd_title_edit, stretch=1)
        jd_layout.addLayout(jd_title_row)

        self.jd_edit = QPlainTextEdit()
        self.jd_edit.setPlaceholderText("粘贴目标岗位的 JD 文本（岗位职责、任职要求等）…")
        self.jd_edit.textChanged.connect(self.on_jd_changed)
        jd_layout.addWidget(self.jd_edit, stretch=1)

        jd_bottom_row = QHBoxLayout()
        self.jd_count_label = QLabel("字符数：0　预估 Token：0")
        self.jd_count_label.setObjectName("jdCountLabel")
        self.clean_jd_button = QPushButton("粘贴并清理（去除公司介绍等无关内容）")
        self.clean_jd_button.setObjectName("secondaryButton")
        self.clean_jd_button.clicked.connect(self.on_clean_jd)
        jd_bottom_row.addWidget(self.jd_count_label, stretch=1)
        jd_bottom_row.addWidget(self.clean_jd_button)
        jd_layout.addLayout(jd_bottom_row)
        columns.addWidget(jd_box, stretch=6)

        root_layout.addLayout(columns, stretch=1)

        # ---- ③ 改写尺度选择 ----
        level_box = QGroupBox("③ 改写尺度选择")
        level_layout = QHBoxLayout(level_box)
        level_layout.setContentsMargins(14, 10, 14, 12)
        self.radio_conservative = QRadioButton("保守\n润色微调，不增经历\n同行业优化")
        self.radio_moderate = QRadioButton("中度\n结构重构，适度增补\n跨细分方向")
        self.radio_deep = QRadioButton("深度\n经历映射，大幅重构\n跨行业")
        self.radio_moderate.setChecked(True)  # PRD 5.1：默认中度
        for radio in (self.radio_conservative, self.radio_moderate, self.radio_deep):
            radio.setObjectName("levelRadio")
            level_layout.addWidget(radio, stretch=1)
        root_layout.addWidget(level_box)

        # ---- 开始优化按钮 ----
        self.start_button = QPushButton("开始优化简历")
        self.start_button.setObjectName("primaryButton")
        self.start_button.setMinimumHeight(52)
        self.start_button.clicked.connect(self.on_start_optimize)
        root_layout.addWidget(self.start_button)

        # ---- 状态栏 ----
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.setCentralWidget(central)

    # ==================================================================
    # 文件选择 / JD 输入
    # ==================================================================

    def on_file_selected(self, path: str) -> None:
        """上传简历后即时解析并展示结果（PRD 3.2.1）。"""
        path = str(path)
        suffix = Path(path).suffix.lower()
        if suffix == ".doc":
            self.drop_zone.show_error(
                "仅支持 .docx 格式，请在 Word 中将 .doc 另存为 .docx 后再上传"
            )
            self.parsed_doc = None
            self.resume_path = ""
            return
        if suffix != ".docx":
            self.drop_zone.show_error("仅支持 .docx 格式的 Word 文档")
            self.parsed_doc = None
            self.resume_path = ""
            return

        try:
            parsed = parse_docx(path)
        except ResumeParseError as exc:
            self.drop_zone.show_error(str(exc))
            self.parsed_doc = None
            self.resume_path = ""
            return

        self.parsed_doc = parsed
        self.resume_path = path
        self.drop_zone.show_loaded(
            parsed.file_name,
            paragraph_count=len(parsed.paragraphs),
            non_empty=parsed.non_empty_count,
            table_count=parsed.table_count,
        )
        logger.info("简历已加载：%s（%s 段）", path, len(parsed.paragraphs))

    def on_jd_changed(self) -> None:
        text = self.jd_edit.toPlainText()
        chars = len(text)
        tokens = estimate_tokens(text)
        hint = ""
        if 0 < chars < JD_MIN_HINT_CHARS:
            hint = "（内容较少，建议补充完整 JD 以提高优化效果）"
        self.jd_count_label.setText(
            f"字符数：{chars}{hint}　预估 Token：{tokens}"
        )

    def on_clean_jd(self) -> None:
        """"粘贴并清理"（PRD 3.2.2）。"""
        jd_text = self.jd_edit.toPlainText().strip()
        if not jd_text:
            QMessageBox.information(self, "提示", "请先粘贴 JD 文本，再点击清理。")
            return
        api_key = config.load_api_key()
        if not api_key:
            QMessageBox.warning(self, "未配置 API Key", "请先在设置中配置 DeepSeek API Key。")
            self.open_settings()
            return
        settings = config.get_settings()
        self.clean_jd_button.setEnabled(False)
        self.clean_jd_button.setText("AI 正在清理…")
        self._jd_clean_worker = JdCleanWorker(
            api_key, settings["base_url"], settings["model"], jd_text
        )
        self._jd_clean_worker.finished_ok.connect(self._on_jd_cleaned)
        self._jd_clean_worker.failed.connect(self._on_jd_clean_failed)
        self._jd_clean_worker.start()

    def _on_jd_cleaned(self, cleaned: str) -> None:
        self.clean_jd_button.setEnabled(True)
        self.clean_jd_button.setText("粘贴并清理（去除公司介绍等无关内容）")
        self.jd_edit.setPlainText(cleaned)

    def _on_jd_clean_failed(self, message: str) -> None:
        self.clean_jd_button.setEnabled(True)
        self.clean_jd_button.setText("粘贴并清理（去除公司介绍等无关内容）")
        QMessageBox.warning(self, "JD 清理失败", message)

    # ==================================================================
    # 优化流程
    # ==================================================================

    def _current_level(self) -> str:
        if self.radio_conservative.isChecked():
            return "conservative"
        if self.radio_deep.isChecked():
            return "deep"
        return "moderate"

    def on_start_optimize(self) -> None:
        """点击"开始优化简历"（PRD 3.2.4 核心流程）。"""
        if self._optimize_worker and self._optimize_worker.isRunning():
            return

        # ---- 前置校验 ----
        if not self.parsed_doc or not self.resume_path:
            QMessageBox.warning(self, "缺少简历", "请先上传 .docx 格式的简历文件。")
            return
        jd_text = self.jd_edit.toPlainText().strip()
        if not jd_text:
            QMessageBox.warning(self, "缺少岗位要求", "请先粘贴目标岗位的 JD 文本。")
            return
        api_key = config.load_api_key()
        if not api_key:
            QMessageBox.warning(
                self,
                "未配置 API Key",
                "尚未配置 DeepSeek API Key，无法调用 AI 优化。\n请先在弹出的窗口中完成配置。",
            )
            self.open_settings()
            return
        if len(jd_text) < JD_MIN_HINT_CHARS:
            answer = QMessageBox.question(
                self,
                "岗位要求过短",
                "岗位要求内容过少（少于 100 字），建议补充完整以提高优化效果。\n是否仍要继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        if len(jd_text) > JD_MAX_CHARS:
            jd_text = jd_text[:JD_MAX_CHARS]
            QMessageBox.information(
                self,
                "岗位要求过长",
                "岗位要求过长，已自动截取前 10000 字。",
            )

        settings = config.get_settings()
        jd_title = self.jd_title_edit.text().strip() or jd_text[:12]
        request = OptimizeRequest(
            resume_path=self.resume_path,
            jd_text=jd_text,
            jd_title=jd_title,
            rewrite_level=self._current_level(),
            output_dir=settings["export_dir"],
            export_pdf=bool(settings.get("export_pdf", True)),
            export_word=bool(settings.get("export_word", True)),
        )

        # ---- 启动后台线程 + 进度对话框 ----
        self._optimize_worker = OptimizeWorker(
            request, api_key, settings["base_url"], settings["model"]
        )
        self._progress_dialog = OptimizationProgressDialog(self)
        self._progress_dialog.cancelRequested.connect(
            self._optimize_worker.request_cancel
        )
        self._optimize_worker.progress.connect(self._progress_dialog.set_progress)
        self._optimize_worker.finished_ok.connect(self._on_optimize_finished)
        self._optimize_worker.canceled.connect(self._on_optimize_canceled)
        self._optimize_worker.failed.connect(self._on_optimize_failed)
        self.start_button.setEnabled(False)
        self._optimize_worker.start()
        self._progress_dialog.show()

    def _close_progress_dialog(self) -> None:
        dialog = self._progress_dialog
        self._progress_dialog = None
        if dialog is not None:
            # PySide6 不支持无参 disconnect()；deleteLater 销毁对象后
            # 指向它的信号连接由 Qt 自动断开，无需显式 disconnect
            dialog.deleteLater()

    def _on_optimize_finished(self, result) -> None:
        """优化完成 → 弹出对比预览（PRD 5.3）。"""
        self._close_progress_dialog()
        self.start_button.setEnabled(True)
        self._last_result = result
        pdf_note = ""
        if result.pdf_error:
            pdf_note = f"\n\n⚠️ {result.pdf_error}"
        preview = PreviewWindow(result, parent=self)
        preview.confirmed.connect(self._on_export_confirmed)
        preview.regenerateRequested.connect(self._on_regenerate)
        if pdf_note:
            preview.append_note(pdf_note)
        preview.show()

    def _on_optimize_canceled(self) -> None:
        self._close_progress_dialog()
        self.start_button.setEnabled(True)
        self.status_bar.showMessage("已取消本次优化", 5000)

    def _on_optimize_failed(self, message: str) -> None:
        self._close_progress_dialog()
        self.start_button.setEnabled(True)
        QMessageBox.critical(self, "优化失败", message)

    # ==================================================================
    # 预览确认 / 导出
    # ==================================================================

    def _on_export_confirmed(self, result, final_map: dict, final_new: list) -> None:
        """用户在预览窗口确认导出（PRD 3.2.5 / 3.2.8）。"""
        try:
            # 内容被手动微调过 → 重新回填覆盖
            if final_map != result.paragraphs_map or final_new != result.new_paragraphs:
                fill_resume(
                    template_path=result.request.resume_path,
                    output_path=result.docx_path,
                    paragraphs_map=final_map,
                    new_paragraphs=final_new,
                )
                if result.request.export_pdf:
                    try:
                        result.pdf_path = convert_docx_to_pdf(result.docx_path)
                        result.pdf_error = ""
                    except PdfConversionError as exc:
                        result.pdf_path = ""
                        result.pdf_error = str(exc)
            # 保存历史记录（PRD 3.2.9）
            ResumeOptimizer.save_history(result)
        except Exception as exc:
            logger.exception("导出收尾失败")
            QMessageBox.critical(self, "导出失败", f"保存结果时出错：{exc}")
            return

        message = f"Word 文件已生成：\n{result.docx_path}"
        if result.pdf_path:
            message += f"\n\nPDF 文件已生成：\n{result.pdf_path}"
        if result.pdf_error:
            message += f"\n\n⚠️ {result.pdf_error}"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("导出成功")
        box.setText("优化完成并已保存历史记录。")
        box.setInformativeText(message)
        open_folder = box.addButton("打开所在文件夹", QMessageBox.ButtonRole.ActionRole)
        box.addButton("完成", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if box.clickedButton() is open_folder:
            folder = str(Path(result.docx_path).parent)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _on_regenerate(self) -> None:
        """预览窗口请求"重新生成"。"""
        self.start_button.setEnabled(True)
        self.on_start_optimize()

    # ==================================================================
    # 设置 / 历史 / 状态栏
    # ==================================================================

    def open_onboarding(self) -> None:
        """左上角"?"：重新唤起新手指引。"""
        dialog = OnboardingDialog(self)
        dialog.exec()

    # ------------------------------------------------------------------
    # 彩蛋（隐藏功能：连点标题 5 次 + 密码）
    # ------------------------------------------------------------------

    def _on_title_clicked(self) -> None:
        """标题点击计数；3 秒内无点击自动归零，累计 5 次弹出密码框。"""
        self._title_click_count += 1
        self._title_reset_timer.start()  # 每次点击刷新 3 秒重置窗口
        if self._title_click_count >= 5:
            self._reset_title_clicks()
            self._show_easter_egg_prompt()

    def _reset_title_clicks(self) -> None:
        self._title_click_count = 0
        self._title_reset_timer.stop()

    def _show_easter_egg_prompt(self) -> None:
        """密码校验：正确（0914）进入彩蛋；错误或取消则什么都不发生。"""
        from PySide6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(self, " ", "请输入密码：")
        if ok and text.strip() == "0914":
            from .components.easter_egg import EasterEggWindow

            self._easter_egg_window = EasterEggWindow(parent=self)
            self._easter_egg_window.show()
        # 输入错误或取消：直接关闭输入框，无任何反应

    def open_settings(self) -> None:
        dialog = SettingsDialog(self)
        dialog.settingsSaved.connect(self.refresh_status_bar)
        dialog.exec()

    def open_history(self) -> None:
        dialog = HistoryWindow(self)
        dialog.exec()

    def refresh_status_bar(self) -> None:
        settings = config.get_settings()
        model_name = config.AVAILABLE_MODELS.get(settings["model"], settings["model"])
        api_state = "API：已配置" if config.has_api_key() else "API：未配置"
        self.status_bar.showMessage(
            f"状态：就绪　|　模型：{model_name}　|　{api_state}"
        )
