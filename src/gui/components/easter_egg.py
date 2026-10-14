"""彩蛋窗口：雨中倒计时。

触发方式（隐藏功能，不对外文档化）：
在主窗口连点 5 次"简历优化工具"标题 → 弹出密码输入框 → 输入 0914 进入。

页面构成（白底窗口）：
- 上部：src/easter egg/rain.mp4 无声循环播放（模仿 GIF 效果；
  视频 1440x1440 正方形，固定显示区 1:1 填满，无黑边）
- 下部：像素文字"距离郑州下小雨还有："
  （src/easter egg/像素倒计时文字.png 用户原图原样显示，不做任何颜色处理；
  仅做 5:1 精确整数倍缩小（3160x850 → 632x170）适配窗口，字形不扭曲）
  冒号后接实时倒计时，目标时间 2026-11-16 12:00:00（本地时间）。
  倒计时为 88px 粗体等宽数字（视觉高与像素文字匹配），基线按图片内容自动对齐。

容错：视频文件缺失或当前环境不支持解码时降级为占位显示，
窗口其余部分（像素文字与倒计时）不受影响。
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QFont, QFontMetrics, QImage, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout

logger = logging.getLogger(__name__)

#: 倒计时目标时间（本地时区）：2026 年 11 月 16 日 12:00:00
_TARGET_TIME = datetime(2026, 11, 16, 12, 0, 0)

#: 像素文字显示宽度：原图 3160x850 的 1/5（精确整数倍缩小 632x170，
#: 避免非整数倍缩放导致的笔画扭曲；SmoothTransformation 保留细节）
_PIXEL_IMAGE_WIDTH = 632

#: 倒计时字号：88px 粗体等宽数字。
#: 数字视觉高约 62px，与 632px 宽下像素文字视觉高（约 60px）匹配
_COUNTDOWN_PIXEL_SIZE = 70

#: 视频（1440x1440 正方形）固定显示边长：1:1 完全填满，无黑边
_VIDEO_SIZE = 620


def format_remaining_seconds(total_seconds: int) -> str:
    """把剩余秒数格式化为「X天 HH:MM:SS」，负数归零（已到期显示全 0）。"""
    total = max(0, int(total_seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{days}天 {hours:02d}:{minutes:02d}:{seconds:02d}"


def easter_egg_resource(*parts: str) -> Path:
    """解析彩蛋资源路径，兼容开发态与 PyInstaller 打包态。

    开发态：<项目>/src/easter egg/…（本文件位于 src/gui/components/ 下）
    打包态：_MEIPASS/easter egg/…（见 build.spec datas 配置）
    """
    if hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parents[2]  # src/
    return base.joinpath("easter egg", *parts)


def _measure_content_offset(image: QImage) -> int:
    """透明背景图：内容（文字描边/笔画/水滴）最低行距图底的像素数。

    用于倒计时文字的基线对齐（倒计时 label 的 bottom margin）。
    原图为 ARGB32 透明背景，alpha > 32 即视为内容像素
    （覆盖浅色笔画、深色描边与彩色水滴）。
    """
    last_ink_y = 0
    height, width = image.height(), image.width()
    for y in range(height):
        for x in range(width):
            color = image.pixelColor(x, y)
            if color.alpha() > 32:
                last_ink_y = y
                break  # 本行找到内容即继续下一行
    return max(0, height - 1 - last_ink_y)


class EasterEggWindow(QDialog):
    """彩蛋展示窗口：循环雨景视频 + 像素文字倒计时。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🌧")
        self.resize(1400, 880)
        self.setStyleSheet("background-color: #ffffff;")

        self._video_error = False
        self._player = None
        self._video_widget = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 20)
        layout.setSpacing(12)

        # ---- 上部：视频区（无声循环，模仿 GIF）----
        self._video_placeholder = QLabel()
        self._video_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._video_placeholder.setStyleSheet("color:#9ca3af; background:transparent;")
        self._video_placeholder.setVisible(False)
        layout.addWidget(self._video_placeholder, stretch=1)
        self._setup_video()

        # ---- 下部：像素文字 + 实时倒计时 ----
        bottom_row = QHBoxLayout()
        bottom_row.addStretch(1)

        self._pixel_label = QLabel()
        self._pixel_label.setStyleSheet("background: transparent;")
        baseline_offset = self._load_pixel_image()

        self._countdown_label = QLabel(format_remaining_seconds(0))
        countdown_font = QFont("Menlo")
        countdown_font.setStyleHint(QFont.StyleHint.Monospace)
        countdown_font.setBold(True)
        countdown_font.setPixelSize(_COUNTDOWN_PIXEL_SIZE)
        self._countdown_label.setFont(countdown_font)
        # 关键：全局 QSS 的 QWidget{font-size:14px} 通配规则会覆盖 setFont 的字号，
        # 必须在内联样式中显式声明 font-size（内联 QSS 优先级最高）才能生效
        self._countdown_label.setStyleSheet(
            f"font-family:'Menlo', monospace; "
            f"font-size:{_COUNTDOWN_PIXEL_SIZE}px; "
            f"font-weight:800; "
            "color:#1a1a1a; background:transparent;"
        )

        # 基线对齐：
        # 像素图内容底边距图底 baseline_offset；图 label 底对齐行底
        # 倒计时文字（数字无下伸部）的视觉底 ≈ 字体基线，
        # 基线距 label 内容区底 = descent + 行距余量（QFontMetrics 动态计算）
        # 令 文字底 = label底 - margin - 基线空隙 = 图底 - baseline_offset
        # → margin = baseline_offset - 基线空隙
        metrics = QFontMetrics(countdown_font)
        leading = max(0, metrics.lineSpacing() - metrics.ascent() - metrics.descent())
        # 数字无下伸部：文字视觉底 ≈ 基线，基线距 label 内容区底 = descent + 行距
        # （当前 120px 字号 + 632px 图宽参数组合下，纯理论公式经渲染实测精确对齐）
        baseline_gap = metrics.descent() + leading
        bottom_margin = max(0, baseline_offset - baseline_gap)
        self._countdown_label.setContentsMargins(0, 0, 0, bottom_margin)

        # 两个 label 都底对齐行底，消除居中差异
        bottom_row.addWidget(
            self._pixel_label, 0, Qt.AlignmentFlag.AlignBottom
        )
        bottom_row.addSpacing(16)
        bottom_row.addWidget(
            self._countdown_label, 0, Qt.AlignmentFlag.AlignBottom
        )
        bottom_row.addStretch(1)
        layout.addLayout(bottom_row)

        # ---- 每秒刷新倒计时 ----
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._update_countdown)
        self._timer.start()
        self._update_countdown()

    # ------------------------------------------------------------------
    # 视频循环播放
    # ------------------------------------------------------------------

    def _setup_video(self) -> None:
        """加载 rain.mp4 并开始无声循环播放；不可用时降级为占位提示。"""
        layout = self.layout()
        video_path = easter_egg_resource("rain.mp4")
        if not video_path.exists():
            self._show_video_placeholder("（视频资源缺失）")
            return
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            from PySide6.QtMultimediaWidgets import QVideoWidget

            self._video_widget = QVideoWidget()
            # 视频 1440x1440：固定方形显示区完全填满，白色页面上无黑边
            self._video_widget.setFixedSize(_VIDEO_SIZE, _VIDEO_SIZE)
            layout.insertWidget(
                0, self._video_widget, 0, Qt.AlignmentFlag.AlignCenter
            )

            self._player = QMediaPlayer(self)
            audio_output = QAudioOutput(self)
            audio_output.setMuted(True)  # 模仿 GIF：无声循环
            self._player.setAudioOutput(audio_output)
            self._player.setVideoOutput(self._video_widget)
            self._player.setSource(QUrl.fromLocalFile(str(video_path)))

            # 主循环方式：原生无限循环（Qt 6.5+）
            try:
                self._player.setLoops(QMediaPlayer.Loops.Infinite)
            except AttributeError:  # 旧版本枚举位置不同
                pass
            # 兜底：播放到末尾时手动重播
            self._player.mediaStatusChanged.connect(self._on_media_status)
            self._player.errorOccurred.connect(self._on_player_error)
            self._player.play()
        except Exception as exc:
            logger.warning("彩蛋视频初始化失败，降级为占位显示：%s", exc)
            self._show_video_placeholder("（当前环境不支持视频播放）")

    def _show_video_placeholder(self, text: str) -> None:
        self._video_placeholder.setText(text)
        self._video_placeholder.setVisible(True)
        if self._video_widget is not None:
            self._video_widget.setVisible(False)

    def _on_media_status(self, status) -> None:
        """播放到末尾时重播（setLoops 之外的兼容兜底）。"""
        try:
            from PySide6.QtMultimedia import QMediaPlayer

            if (
                status == QMediaPlayer.MediaStatus.EndOfMedia
                and self._player is not None
            ):
                self._player.play()
        except Exception:  # pragma: no cover - QtMultimedia 缺失时不会连接本槽
            pass

    def _on_player_error(self, error, message) -> None:
        """播放失败（编解码不支持等）→ 降级提示，不影响倒计时功能。"""
        if not self._video_error:
            self._video_error = True
            logger.warning("彩蛋视频播放失败：%s", message)
            self._show_video_placeholder("（视频无法播放）")

    # ------------------------------------------------------------------
    # 像素文字
    # ------------------------------------------------------------------

    def _load_pixel_image(self) -> int:
        """加载像素文字图：用户原图原样显示，仅做整数倍缩放。

        不做任何颜色处理（保持原黑底浅字与水滴配色）。

        Returns:
            基线偏移量（图片内容最低行距图底的像素数），
            资源缺失时返回 0。
        """
        image_path = easter_egg_resource("像素倒计时文字.png")
        if not image_path.exists():
            # 资源缺失兜底：用文本呈现同样内容
            self._pixel_label.setText("距离郑州下小雨还有：")
            self._pixel_label.setStyleSheet(
                "color:#1a1a1a; background:transparent; "
                f"font-size:{_COUNTDOWN_PIXEL_SIZE - 30}px; font-weight:800;"
            )
            return 0
        image = QImage(str(image_path))
        if image.isNull():
            logger.warning("像素文字图加载失败：%s", image_path)
            return 0
        # 5:1 精确整数倍缩小（3160x850 → 632x170）；
        # SmoothTransformation 保留细节（最近邻缩放会导致笔画扭曲）
        image = image.scaledToWidth(
            _PIXEL_IMAGE_WIDTH, Qt.TransformationMode.SmoothTransformation
        )
        baseline_offset = _measure_content_offset(image)
        pixmap = QPixmap.fromImage(image)
        self._pixel_label.setPixmap(pixmap)
        self._pixel_label.setFixedSize(pixmap.size())
        return baseline_offset

    # ------------------------------------------------------------------
    # 倒计时
    # ------------------------------------------------------------------

    def _update_countdown(self) -> None:
        remaining = int((_TARGET_TIME - datetime.now()).total_seconds())
        self._countdown_label.setText(format_remaining_seconds(remaining))

    # ------------------------------------------------------------------
    # 资源释放
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._timer.stop()
        if self._player is not None:
            self._player.stop()
        super().closeEvent(event)