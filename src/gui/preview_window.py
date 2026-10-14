"""优化结果对比预览窗口（PRD 3.2.8 / 5.3）。

- 顶部：改写摘要 + 修改/新增统计
- 中部：左右分栏差异对比（绿色=新增，红色=删除，黄色=修改）
- 底部：[手动微调]（在 DiffViewer 内） [重新生成] [确认导出]
- 用户可在预览界面直接编辑优化后的内容再导出
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import config
from .components.diff_viewer import DiffViewer


class PreviewWindow(QDialog):
    """优化结果预览窗口（非模态，便于用户与主窗口交互）。"""

    #: 确认导出：参数为 (result, 微调后的 paragraphs_map, 微调后的 new_paragraphs)
    confirmed = Signal(object, dict, list)
    #: 用户请求重新生成
    regenerateRequested = Signal()

    def __init__(self, result, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("优化结果预览")
        self.resize(1080, 760)
        self.setModal(False)
        self._result = result

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # ---- 摘要区 ----
        level_name = config.REWRITE_LEVELS.get(
            result.request.rewrite_level, result.request.rewrite_level
        )
        stats = {
            "modified": result.modified_count,
            "added": result.inserted_count,
        }
        header = QLabel(f"改写尺度：{level_name}　|　模型：{result.model}")
        header.setObjectName("previewHeader")
        summary_text = result.summary or "（AI 未提供改写摘要）"
        self.summary_label = QLabel(f"改写摘要：{summary_text}")
        self.summary_label.setWordWrap(True)
        layout.addWidget(header)
        layout.addWidget(self.summary_label)

        # ---- 对比视图 ----
        self.diff_viewer = DiffViewer(
            original=result.original_paragraphs,
            paragraphs_map=result.paragraphs_map,
            new_paragraphs=result.new_paragraphs,
            parent=self,
        )
        viewer_stats = self.diff_viewer.stats
        stats_label = QLabel(
            f"共修改 {viewer_stats['modified']} 段，"
            f"新增 {viewer_stats['added']} 段，"
            f"删除 {viewer_stats['cleared']} 段，"
            f"未改动 {viewer_stats['unchanged']} 段"
        )
        stats_label.setObjectName("previewStats")
        layout.addWidget(stats_label)
        layout.addWidget(self.diff_viewer, stretch=1)

        # ---- 底部操作 ----
        buttons_row = QHBoxLayout()
        buttons_row.addStretch(1)
        self.regenerate_button = QPushButton("重新生成")
        self.regenerate_button.setObjectName("secondaryButton")
        self.regenerate_button.clicked.connect(self._on_regenerate)
        export_text = "确认导出 Word + PDF" if result.request.export_pdf else "确认导出 Word"
        self.confirm_button = QPushButton(export_text)
        self.confirm_button.setObjectName("primaryButton")
        self.confirm_button.setMinimumHeight(44)
        self.confirm_button.clicked.connect(self._on_confirm)
        buttons_row.addWidget(self.regenerate_button)
        buttons_row.addWidget(self.confirm_button)
        layout.addLayout(buttons_row)

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------

    def append_note(self, text: str) -> None:
        """追加提示信息（如 PDF 转换警告）。"""
        note = QLabel(text)
        note.setWordWrap(True)
        note.setStyleSheet("color:#b45309;")
        self.layout().insertWidget(2, note)

    def _on_regenerate(self) -> None:
        self.regenerateRequested.emit()
        self.close()

    def _on_confirm(self) -> None:
        # 提取（可能经过手动微调的）最终内容
        final_map, final_new = self.diff_viewer.get_result()
        self.confirmed.emit(self._result, final_map, final_new)
        self.close()