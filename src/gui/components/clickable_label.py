"""可点击的 QLabel 组件。

用于主窗口标题等需要响应点击的静态文本
（彩蛋入口：标题连点 5 次，PRD 未公开的隐藏功能）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel


class ClickableLabel(QLabel):
    """点击时发出 clicked 信号的 QLabel。

    注意：不改变鼠标光标形态（彩蛋入口不能露出可点击的视觉线索）。
    """

    clicked = Signal()

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)