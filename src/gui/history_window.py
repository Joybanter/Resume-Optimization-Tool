"""历史记录窗口（PRD 3.2.9）。

- 按时间倒序展示优化记录
- 支持 JD 关键词搜索
- 可打开生成的 Word / PDF 文件
- 可删除记录（可选同时删除生成文件）
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import config
from ..core.history_db import HistoryDB
from ..core.pdf_converter import open_file_in_system


class HistoryWindow(QDialog):
    """历史记录管理窗口。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("历史记录")
        self.resize(900, 560)
        self.db = HistoryDB()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        # ---- 搜索行 ----
        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("按 JD 关键词搜索…（回车刷新）")
        self.search_edit.returnPressed.connect(self.refresh)
        self.search_button = QPushButton("搜索")
        self.search_button.setObjectName("secondaryButton")
        self.search_button.clicked.connect(self.refresh)
        search_row.addWidget(self.search_edit, stretch=1)
        search_row.addWidget(self.search_button)
        layout.addLayout(search_row)

        # ---- 记录表 ----
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["时间", "岗位名称", "改写尺度", "模型", "Word 文件"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        self.table.setColumnWidth(0, 150)
        self.table.setColumnWidth(1, 130)
        self.table.setColumnWidth(2, 80)
        self.table.setColumnWidth(3, 170)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        layout.addWidget(self.table, stretch=1)

        # ---- 详情区 ----
        self.detail_label = QLabel("选择一条记录查看详情")
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet("color:#6b7280;")
        layout.addWidget(self.detail_label)

        # ---- 操作按钮 ----
        actions_row = QHBoxLayout()
        self.open_docx_button = QPushButton("打开 Word 文件")
        self.open_docx_button.setEnabled(False)
        self.open_docx_button.clicked.connect(self._on_open_docx)
        self.open_pdf_button = QPushButton("打开 PDF 文件")
        self.open_pdf_button.setEnabled(False)
        self.open_pdf_button.clicked.connect(self._on_open_pdf)
        self.delete_button = QPushButton("删除记录")
        self.delete_button.setObjectName("secondaryButton")
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self._on_delete)
        self.close_button = QPushButton("关闭")
        self.close_button.setObjectName("secondaryButton")
        self.close_button.clicked.connect(self.accept)
        actions_row.addWidget(self.open_docx_button)
        actions_row.addWidget(self.open_pdf_button)
        actions_row.addWidget(self.delete_button)
        actions_row.addStretch(1)
        actions_row.addWidget(self.close_button)
        layout.addLayout(actions_row)

        self._records: list[dict] = []
        self.refresh()

    # ==================================================================
    # 数据展示
    # ==================================================================

    def refresh(self) -> None:
        keyword = self.search_edit.text().strip()
        self._records = self.db.list_records(keyword=keyword or None)
        self.table.setRowCount(0)
        for row_index, record in enumerate(self._records):
            self.table.insertRow(row_index)
            values = [
                record.get("created_at", ""),
                record.get("jd_title", ""),
                config.REWRITE_LEVELS.get(
                    record.get("rewrite_level", ""), record.get("rewrite_level", "")
                ),
                record.get("model", ""),
                record.get("output_docx", ""),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col in (0, 1, 2, 3):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                # 记录 ID 放入 item data，避免依赖行号
                item.setData(Qt.ItemDataRole.UserRole, record.get("id"))
                self.table.setItem(row_index, col, item)
        self._on_row_selected()

    def _selected_record(self) -> dict | None:
        selected = self.table.selectedItems()
        if not selected:
            return None
        record_id = selected[0].data(Qt.ItemDataRole.UserRole)
        for record in self._records:
            if record.get("id") == record_id:
                return record
        return None

    def _on_row_selected(self) -> None:
        record = self._selected_record()
        has = record is not None
        self.open_docx_button.setEnabled(has and bool(record.get("output_docx")))
        self.open_pdf_button.setEnabled(has and bool(record.get("output_pdf")))
        self.delete_button.setEnabled(has)
        if not has:
            self.detail_label.setText("选择一条记录查看详情")
            return
        jd_summary = record.get("jd_summary", "") or "（无摘要）"
        summary = record.get("summary", "") or "（无改写摘要）"
        self.detail_label.setText(
            f"JD 摘要：{jd_summary[:120]}…\n改写摘要：{summary}"
        )

    # ==================================================================
    # 操作
    # ==================================================================

    def _require_existing(self, path: str) -> str | None:
        if not path:
            QMessageBox.information(self, "提示", "该记录没有生成此类型的文件。")
            return None
        if not Path(path).exists():
            QMessageBox.warning(self, "文件不存在", f"文件已被移动或删除：\n{path}")
            return None
        return path

    def _on_open_docx(self) -> None:
        record = self._selected_record()
        if not record:
            return
        path = self._require_existing(record.get("output_docx", ""))
        if path:
            open_file_in_system(path)

    def _on_open_pdf(self) -> None:
        record = self._selected_record()
        if not record:
            return
        path = self._require_existing(record.get("output_pdf", ""))
        if path:
            open_file_in_system(path)

    def _on_delete(self) -> None:
        """删除记录，并询问是否同时删除生成文件（PRD 3.2.9）。"""
        record = self._selected_record()
        if not record:
            return
        answer = QMessageBox.question(
            self,
            "删除记录",
            "确定删除这条优化记录吗？\n\n是否同时删除生成的文件？",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return
        delete_files = answer == QMessageBox.StandardButton.Yes

        if delete_files:
            for key in ("output_docx", "output_pdf"):
                path = record.get(key, "")
                if path:
                    try:
                        Path(path).unlink(missing_ok=True)
                    except OSError:
                        pass

        self.db.delete_record(record.get("id"))
        self.refresh()