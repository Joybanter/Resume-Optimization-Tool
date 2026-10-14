"""首次启动引导 / 新手指引对话框（PRD 3.2.7 / 5.5）。

两个入口：
- 首次启动检测到无 API Key 时自动弹出（src/main.py）
- 主界面左上角"?"按钮随时重新唤起（本次新增）

内容：
- 工具简介（PRD 1.1 / 1.2 核心价值）
- 推荐使用方式：上传 → JD → 尺度 → 预览微调 → 导出（PRD 1.3 设计原则）
- DeepSeek API Key 获取详细步骤（注册 → 创建 Key → 充值说明）
- Key 验证与保存：验证通过自动保存，失败提示具体原因
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import config
from .settings_dialog import TestConnectionWorker


class OnboardingDialog(QDialog):
    """新手指引对话框（含 API Key 配置）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新手指引")
        self.setMinimumWidth(640)
        self.setMinimumHeight(580)
        self._test_worker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)

        title = QLabel("欢迎使用简历优化工具")
        title.setObjectName("onboardingTitle")
        layout.addWidget(title)

        # ---- 说明区（可滚动）----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_content = QWidget()
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setContentsMargins(4, 4, 12, 4)
        content_layout.setSpacing(14)

        content_layout.addWidget(self._section_label(
            "这个工具做什么？",
            "上传你的 Word 简历 + 粘贴目标岗位 JD，AI 会理解两者，"
            "并把简历定向改写为更匹配该岗位的版本，同时完整保留你原简历的排版格式。"
        ))
        content_layout.addWidget(self._usage_widget())
        content_layout.addWidget(self._api_key_widget())
        content_layout.addWidget(self._section_label(
            "安全与隐私",
            "API Key 仅加密存储在本机（仅当前系统用户可解密）；"
            "简历数据不经过任何中间服务器，直接从本机发送到 DeepSeek 官方 API。"
        ))
        content_layout.addStretch(1)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, stretch=1)

        # ---- Key 输入与验证 ----
        key_row = QHBoxLayout()
        key_label = QLabel("API Key：")
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("sk-…（粘贴你的 DeepSeek API Key）")
        # 已配置用户重新打开指引时预填，便于查看 / 更新
        existing_key = config.load_api_key()
        if existing_key:
            self.key_edit.setText(existing_key)
        key_row.addWidget(key_label)
        key_row.addWidget(self.key_edit, stretch=1)
        layout.addLayout(key_row)

        self.verify_button = QPushButton("验证并开始使用")
        self.verify_button.setObjectName("primaryButton")
        self.verify_button.setMinimumHeight(44)
        self.verify_button.clicked.connect(self.on_verify)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        bottom_row = QHBoxLayout()
        self.skip_button = QPushButton("稍后配置（先浏览界面）")
        self.skip_button.setObjectName("secondaryButton")
        self.skip_button.clicked.connect(self._on_skip)
        bottom_row.addWidget(self.skip_button, stretch=1)
        bottom_row.addWidget(self.verify_button)
        layout.addLayout(bottom_row)

    # ------------------------------------------------------------------
    # 内容区块构建
    # ------------------------------------------------------------------

    @staticmethod
    def _section_label(heading: str, body: str) -> QLabel:
        label = QLabel(
            f"<b style='color:#111827;font-size:15px;'>{heading}</b><br>{body}"
        )
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setStyleSheet("color:#4b5563;")
        return label

    @staticmethod
    def _link(text: str, url: str) -> str:
        return f"<a href='{url}' style='color:#2563eb;'>{text}</a>"

    def _usage_widget(self) -> QGroupBox:
        """推荐使用方式（PRD 1.3：极简操作，全程 3 步）。"""
        box = QGroupBox("推荐使用方式")
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(14, 10, 14, 10)
        usage = QLabel(
            "<b>第一步</b>　上传 .docx 简历（支持拖拽，原排版会被完整保留）<br>"
            "<b>第二步</b>　粘贴目标岗位 JD，可点「粘贴并清理」去除公司介绍等无关内容<br>"
            "<b>第三步</b>　选择改写尺度：<br>"
            "　　　　　• 保守（润色微调）— 推荐首次使用，或同行业相近岗位<br>"
            "　　　　　• 中度（结构重构）— 跨细分方向<br>"
            "　　　　　• 深度（经历映射）— 跨行业 / 跨岗位方向<br>"
            "<b>第四步</b>　开始优化 → 在预览窗口核对修改"
            "（绿色=新增，黄色=修改，红色=删除），支持手动微调，"
            "确认后导出 Word / PDF"
        )
        usage.setWordWrap(True)
        usage.setTextFormat(Qt.TextFormat.RichText)
        usage.setStyleSheet("color:#4b5563;")
        box_layout.addWidget(usage)

        tips = QLabel(
            "小提示：每次只针对一个岗位优化效果最好；JD 越完整效果越好；"
            "重要投递前建议用 Word 打开终稿再确认一遍格式。"
        )
        tips.setWordWrap(True)
        tips.setStyleSheet(
            "color:#92400e; background:#fef3c7; border-radius:6px; padding:8px;"
        )
        box_layout.addWidget(tips)
        return box

    def _api_key_widget(self) -> QGroupBox:
        """获取 DeepSeek API Key 的详细步骤（PRD 3.2.7）。"""
        box = QGroupBox("如何获得 DeepSeek API Key")
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(14, 10, 14, 10)
        steps = QLabel(
            f"<b>第一步</b>　注册 DeepSeek 开放平台账号　"
            f"{self._link('点击前往注册 →', 'https://platform.deepseek.com')}<br>"
            f"<b>第二步</b>　登录后创建 API Key　"
            f"{self._link('点击前往创建 →', 'https://platform.deepseek.com/api_keys')}<br>"
            "　　　　　　　创建后会得到一串 <b>sk-</b> 开头的密钥，请立即复制保存"
            "（页面关闭后无法再次查看完整 Key）。<br>"
            "　　　　　　　若提示余额不足，先充值少量金额即可"
            "（约 ¥10 可优化数百次简历）。<br>"
            "<b>第三步</b>　将 Key 粘贴到下方输入框，点击「验证并开始使用」"
        )
        steps.setWordWrap(True)
        steps.setTextFormat(Qt.TextFormat.RichText)
        steps.setOpenExternalLinks(True)
        steps.setStyleSheet("color:#4b5563;")
        box_layout.addWidget(steps)
        return box

    # ------------------------------------------------------------------
    # 验证与保存（PRD 3.2.7）
    # ------------------------------------------------------------------

    def on_verify(self) -> None:
        api_key = self.key_edit.text().strip()
        if not api_key:
            self.status_label.setText("✗ 请先填写 API Key")
            return
        if self._test_worker and self._test_worker.isRunning():
            return
        self.verify_button.setEnabled(False)
        self.status_label.setText("正在验证 API Key…")
        settings = config.get_settings()
        self._test_worker = TestConnectionWorker(
            api_key, settings["base_url"], settings["model"]
        )
        self._test_worker.finished_ok.connect(self._on_verify_done)
        self._test_worker.start()

    def _on_verify_done(self, ok: bool, message: str) -> None:
        self.verify_button.setEnabled(True)
        if not ok:
            # PRD 3.2.7：验证失败提示具体原因
            self.status_label.setText(f"✗ {message}")
            QMessageBox.warning(self, "验证失败", message)
            return
        try:
            config.save_api_key(self.key_edit.text().strip())
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", f"API Key 保存失败：{exc}")
            return
        self.accept()

    def _on_skip(self) -> None:
        self.reject()