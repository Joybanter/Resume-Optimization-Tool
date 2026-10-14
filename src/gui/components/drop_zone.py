"""拖拽上传区域组件（PRD 3.2.1 / 5.1）。

支持两种上传方式：
- 拖拽 .docx 文件到区域
- 点击区域打开文件选择对话框

拖入非 .docx 文件时即时提示（PRD 8），.doc 给出另存为 .docx 的引导。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QFrame, QLabel, QVBoxLayout


class DropZone(QFrame):
    """简历文件拖拽 / 点击上传区域。"""

    fileDropped = Signal(str)  # 参数：文件绝对路径

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(6)

        self._icon_label = QLabel("📄")
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setStyleSheet("font-size: 34px; background: transparent; border: none;")

        self._hint_label = QLabel("拖拽 .docx 简历文件到此处\n或点击选择文件")
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint_label.setStyleSheet("background: transparent; border: none;")
        self._hint_label.setWordWrap(True)

        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet(
            "background: transparent; border: none; color: #2563eb; font-weight: 600;"
        )
        self._status_label.setWordWrap(True)

        layout.addStretch(1)
        layout.addWidget(self._icon_label)
        layout.addWidget(self._hint_label)
        layout.addWidget(self._status_label)
        layout.addStretch(1)

    # ------------------------------------------------------------------
    # 拖拽事件
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.mimeData() and event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    suffix = Path(url.toLocalFile()).suffix.lower()
                    if suffix in (".docx", ".doc"):
                        event.acceptProposedAction()
                        return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                self.fileDropped.emit(path)
                event.acceptProposedAction()
                return
        event.ignore()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择简历文件",
            str(Path.home()),
            "Word 文档 (*.docx)",
        )
        if path:
            self.fileDropped.emit(path)

    # ------------------------------------------------------------------
    # 状态展示
    # ------------------------------------------------------------------

    def show_loaded(
        self, file_name: str, paragraph_count: int, non_empty: int, table_count: int
    ) -> None:
        """显示已上传 / 解析成功状态（PRD 5.1）。"""
        self._icon_label.setText("✅")
        self._hint_label.setText(f"已上传：{file_name}")
        detail = f"解析成功 · 共 {paragraph_count} 段"
        if table_count:
            detail += f"（含 {table_count} 个表格）"
        self._status_label.setText(detail)
        self.setProperty("loaded", True)
        self.style().unpolish(self)
        self.style().polish(self)

    def show_error(self, message: str) -> None:
        """显示解析失败状态。"""
        self._icon_label.setText("⚠️")
        self._hint_label.setText(message)
        self._status_label.setText("")
        self.setProperty("loaded", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def clear(self) -> None:
        """恢复初始未上传状态。"""
        self._icon_label.setText("📄")
        self._hint_label.setText("拖拽 .docx 简历文件到此处\n或点击选择文件")
        self._status_label.setText("")
        self.setProperty("loaded", False)
        self.style().unpolish(self)
        self.style().polish(self)