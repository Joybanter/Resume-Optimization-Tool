"""优化对比查看器组件（PRD 3.2.8 / 5.3）。

左右分栏对比原文与优化后内容：
- 左栏：原始简历段落
- 右栏：优化后段落
- 差异高亮：绿色=新增，红色=删除，黄色=修改（PRD 3.2.8）

支持"手动微调"：切换到编辑模式（右侧变为纯文本编辑框，
每段一行，格式 `[段落ID] 内容`），编辑后可提取新的改写结果。
"""

from __future__ import annotations

import html
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

#: 状态 → 高亮样式（PRD 3.2.8 配色）
_STYLE = {
    "unchanged": ("#ffffff", "#374151", "无变化"),
    "modified": ("#fef3c7", "#1f2937", "已修改"),
    "added": ("#dcfce7", "#1f2937", "新增"),
    "cleared": ("#fee2e2", "#1f2937", "已删除"),
}

_LEFT_PLACEHOLDER = {
    "added": "（此处新增内容）",
    "cleared": "",
}

#: 编辑模式行解析：`[p12] 内容`
_LINE_RE = re.compile(r"^\[([A-Za-z0-9_]+)\]\s?(.*)$", re.DOTALL)


def _make_entries(
    original: list[tuple[str, str]],
    paragraphs_map: dict[str, str],
    new_paragraphs: list[dict],
) -> list[dict]:
    """按展示顺序合并原段落与新增段落，并标注差异状态。"""
    entries: list[dict] = []

    original_ids = [pid for pid, _ in original]
    # 原段落
    for para_id, text in original:
        if para_id not in paragraphs_map:
            entries.append(
                {
                    "id": para_id,
                    "kind": "orig",
                    "original": text,
                    "modified": text,
                    "status": "unchanged",
                    "anchor": "",
                }
            )
            continue
        new_text = paragraphs_map[para_id]
        if not str(new_text).strip() and text.strip():
            status = "cleared"
        elif str(new_text) == text:
            status = "unchanged"
        else:
            status = "modified"
        entries.append(
            {
                "id": para_id,
                "kind": "orig",
                "original": text,
                "modified": str(new_text),
                "status": status,
                "anchor": "",
            }
        )

    # 新增段落：插入到锚点段之后（保持 new_paragraphs 相对顺序）
    for i, item in enumerate(new_paragraphs):
        entry = {
            "id": item.get("id") or f"new_{i + 1}",
            "kind": "new",
            "original": "",
            "modified": str(item.get("content", "")),
            "status": "added",
            "anchor": item.get("insert_after", ""),
        }
        anchor = entry["anchor"]
        if anchor:
            # 找到该锚点最后一个条目的位置，插入其后（同锚点多条依次排）
            insert_at = None
            for idx in range(len(entries) - 1, -1, -1):
                if entries[idx]["id"] == anchor:
                    insert_at = idx + 1
                    break
            if insert_at is not None:
                entries.insert(insert_at, entry)
                continue
        # 锚点不存在（或未指定）→ 追加末尾
        entries.append(entry)

    return entries


class DiffViewer(QWidget):
    """左右分栏差异对比视图，支持切换编辑模式。"""

    def __init__(
        self,
        original: list[tuple[str, str]],
        paragraphs_map: dict[str, str],
        new_paragraphs: list[dict],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._original = list(original)
        self._map = dict(paragraphs_map)
        self._new = [dict(item) for item in new_paragraphs]
        self._editable = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._toggle_button = QPushButton("✎ 手动微调")
        self._toggle_button.setObjectName("secondaryButton")
        self._toggle_button.clicked.connect(self.toggle_editable)
        self._toggle_button.setMaximumWidth(120)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        self._left_view = QTextBrowser()
        self._left_view.setOpenExternalLinks(False)
        self._right_view = QTextBrowser()
        self._right_view.setOpenExternalLinks(False)
        self._right_edit = QPlainTextEdit()
        self._right_edit.setVisible(False)
        self._right_edit.setPlaceholderText("可直接编辑，每段一行，行首保留 [段落ID] 标记")

        self._splitter.addWidget(self._left_view)
        self._splitter.addWidget(self._right_view)
        self._splitter.addWidget(self._right_edit)
        self._splitter.setSizes([1, 1])

        layout.addWidget(self._toggle_button, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._splitter, stretch=1)

        self.refresh()

    # ------------------------------------------------------------------
    # 展示
    # ------------------------------------------------------------------

    def _entry_html(self, entry: dict, side: str) -> str:
        status = entry["status"]
        bg, fg, _ = _STYLE[status]
        if side == "left":
            text = entry["original"]
            if entry["status"] == "added":
                text = _LEFT_PLACEHOLDER["added"]
        else:
            text = entry["modified"]
            if entry["status"] == "cleared":
                text = "（该段已删除）"
        if not str(text).strip():
            text = "　"  # 保持空段占位可见
        safe = html.escape(str(text))
        badge = (
            f'<span style="color:#9ca3af;font-size:11px;">[{html.escape(entry["id"])}]</span> '
            if entry["kind"] == "new"
            else ""
        )
        return (
            f'<div style="background:{bg};color:{fg};padding:6px 10px;'
            f'margin:0;border-bottom:1px solid #f3f4f6;white-space:pre-wrap;'
            f'font-size:13px;line-height:1.6;">{badge}{safe}</div>'
        )

    def refresh(self) -> None:
        """根据当前数据与模式刷新视图。"""
        entries = _make_entries(self._original, self._map, self._new)
        left_html = "".join(self._entry_html(e, "left") for e in entries)
        right_html = "".join(self._entry_html(e, "right") for e in entries)
        self._left_view.setHtml(
            f'<html><body style="margin:0;">{left_html}</body></html>'
        )
        self._right_view.setHtml(
            f'<html><body style="margin:0;">{right_html}</body></html>'
        )

        if self._editable:
            self._right_edit.setPlainText(self._build_edit_text())

    def _build_edit_text(self) -> str:
        entries = _make_entries(self._original, self._map, self._new)
        lines = []
        for entry in entries:
            text = entry["modified"] if entry["status"] != "cleared" else ""
            lines.append(f"[{entry['id']}] {text}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 编辑模式
    # ------------------------------------------------------------------

    def toggle_editable(self) -> None:
        self.set_editable(not self._editable)

    def set_editable(self, editable: bool) -> None:
        if editable:
            # 进入编辑前，把（可能已编辑过的）内容解析回数据，保证起点一致
            if self._editable:
                self.apply_edits()
            self._editable = True
            self._right_view.setVisible(False)
            self._right_edit.setVisible(True)
            self._right_edit.setPlainText(self._build_edit_text())
            self._toggle_button.setText("✓ 完成微调")
        else:
            self.apply_edits()
            self._editable = False
            self._right_edit.setVisible(False)
            self._right_view.setVisible(True)
            self.refresh()
            self._toggle_button.setText("✎ 手动微调")

    def apply_edits(self) -> bool:
        """把编辑框中的文本解析回内部数据。返回是否有解析错误。"""
        if not self._editable:
            return False
        known_ids = {pid for pid, _ in self._original}
        new_anchors = {item.get("id", f"new_{i+1}"): item.get("insert_after", "")
                       for i, item in enumerate(self._new)}
        new_ids = set(new_anchors.keys())

        new_map: dict[str, str] = {}
        new_paragraphs: list[dict] = []
        has_error = False
        last_id = None
        for line in self._right_edit.toPlainText().splitlines():
            if not line.strip():
                continue
            match = _LINE_RE.match(line.strip())
            if not match:
                # 无 ID 前缀的行：追加到上一段落（允许段落内换行）
                if last_id is None:
                    has_error = True
                    continue
                target = new_map if last_id in known_ids else None
                if target is not None and last_id in new_map:
                    new_map[last_id] += "\n" + line
                else:
                    for item in new_paragraphs:
                        if item.get("id") == last_id:
                            item["content"] += "\n" + line
                continue
            para_id, text = match.group(1), match.group(2)
            if para_id in known_ids:
                new_map[para_id] = text
                last_id = para_id
            elif para_id in new_ids:
                new_paragraphs.append(
                    {
                        "id": para_id,
                        "insert_after": new_anchors.get(para_id, ""),
                        "content": text,
                    }
                )
                last_id = para_id
            else:
                has_error = True
        self._map = new_map
        self._new = new_paragraphs
        return has_error

    # ------------------------------------------------------------------
    # 结果提取与统计
    # ------------------------------------------------------------------

    def get_result(self) -> tuple[dict[str, str], list[dict]]:
        """提取当前（可能微调过的）改写结果。

        Returns:
            (paragraphs_map, new_paragraphs)
        """
        if self._editable:
            self.apply_edits()
        return dict(self._map), [dict(x) for x in self._new]

    @property
    def stats(self) -> dict[str, int]:
        entries = _make_entries(self._original, self._map, self._new)
        return {
            "modified": sum(1 for e in entries if e["status"] == "modified"),
            "added": sum(1 for e in entries if e["status"] == "added"),
            "cleared": sum(1 for e in entries if e["status"] == "cleared"),
            "unchanged": sum(1 for e in entries if e["status"] == "unchanged"),
        }