"""优化进度对话框组件（PRD 5.2）。

显示进度条、当前步骤说明，支持取消。优化任务在后台 QThread 中运行，
通过 setProgress 接收进度回调（线程安全：Qt 信号跨线程排队）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

#: 阶段对应的步骤序号（PRD 5.2：第 x/2 步）
_STAGE_STEP = {"parse": "", "analyze": "（第 1/2 步）", "rewrite": "（第 2/2 步）"}


class OptimizationProgressDialog(QDialog):
    """优化过程中的模态进度对话框。"""

    cancelRequested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("正在优化简历")
        self.setModal(True)
        self.setMinimumWidth(460)
        # 进度对话框不允许用户通过关闭按钮绕过取消流程
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        title = QLabel("正在优化简历…")
        title.setObjectName("progressTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)

        self.step_label = QLabel("正在准备…")
        self.step_label.setObjectName("progressStep")
        self.step_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.step_label.setWordWrap(True)

        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("secondaryButton")
        self.cancel_button.clicked.connect(self._on_cancel)

        layout.addWidget(title)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.step_label)
        layout.addWidget(self.cancel_button, alignment=Qt.AlignmentFlag.AlignCenter)

        self._canceled = False

    # ------------------------------------------------------------------
    # 外部接口
    # ------------------------------------------------------------------

    def set_progress(self, percent: int, stage: str, message: str) -> None:
        """更新进度（由后台线程通过信号调用）。"""
        percent = max(0, min(100, int(percent)))
        self.progress_bar.setValue(percent)
        suffix = _STAGE_STEP.get(stage, "")
        self.step_label.setText(f"{message}{suffix}")

    @property
    def canceled(self) -> bool:
        return self._canceled

    # ------------------------------------------------------------------
    # 取消
    # ------------------------------------------------------------------

    def _on_cancel(self) -> None:
        if self._canceled:
            return
        self._canceled = True
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("正在取消…")
        self.step_label.setText("正在取消，请稍候…")
        self.cancelRequested.emit()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        # 关闭窗口视同点击取消
        self._on_cancel()
        event.accept()