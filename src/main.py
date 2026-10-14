"""程序入口（PRD 4.1 整体架构 / 5.5 首次启动引导）。

运行方式：
- 开发调试：项目根目录执行 `python -m src.main`
- 打包发布：PyInstaller 打包为桌面程序（见 build.spec）

首次启动检测到无 API Key 时弹出引导对话框（PRD 3.2.7）。
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler


def _setup_logging() -> None:
    """日志写入用户数据目录，便于排障（PRD 8：回填异常等记录日志）。"""
    from src import config

    config.ensure_app_dir()
    log_file = config.APP_DIR / "app.log"
    handler = RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # 打包后无控制台，开发态保留控制台输出
    if sys.stderr is not None:
        root.addHandler(logging.StreamHandler(sys.stderr))


def _load_stylesheet(app) -> None:
    """加载 QSS 样式表（兼容开发态与 PyInstaller 打包态资源路径）。"""
    from pathlib import Path

    if hasattr(sys, "_MEIPASS"):  # PyInstaller 单文件解压目录
        qss_path = Path(sys._MEIPASS) / "resources" / "style.qss"
    else:
        qss_path = Path(__file__).resolve().parent.parent / "src" / "resources" / "style.qss"
        if not qss_path.exists():
            qss_path = Path(__file__).resolve().parent / "resources" / "style.qss"
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))


def main() -> int:
    _setup_logging()
    logger = logging.getLogger(__name__)

    from PySide6.QtWidgets import QApplication

    from src import config
    from src.gui.main_window import MainWindow
    from src.gui.onboarding_dialog import OnboardingDialog

    app = QApplication(sys.argv)
    app.setApplicationName("简历优化工具")
    app.setOrganizationName("ResumeOptimizer")
    _load_stylesheet(app)

    # ---- 首次启动引导（PRD 3.2.7 / 5.5）----
    if not config.has_api_key():
        logger.info("未检测到 API Key，启动首次引导")
        onboarding = OnboardingDialog()
        onboarding.exec()  # 用户选择"稍后配置"时也允许进入主界面

    window = MainWindow()
    window.show()
    logger.info("应用启动完成")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())