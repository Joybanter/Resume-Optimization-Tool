"""PDF 导出模块（PRD 3.2.6 / 4.2）。

使用 docx2pdf 调用本机已安装的 Microsoft Word（或 WPS）完成转换，
转换保真度最高。docx2pdf 仅在安装了 Word 的环境可用：
- Windows：通过 COM 调用 Word/WPS
- macOS：通过 AppleScript 调用 Microsoft Word for Mac
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class PdfConversionError(Exception):
    """PDF 转换失败，message 中包含用户可读的原因与建议。"""


def is_word_available() -> bool:
    """检测本机是否安装了 Microsoft Word（docx2pdf 的运行依赖）。

    Windows 下检测注册表中 Word.Application 的 AppID；
    macOS 下检测 /Applications 中的 Word 程序。
    """
    system = platform.system()
    try:
        if system == "Windows":
            import winreg  # type: ignore

            try:
                with winreg.OpenKey(
                    winreg.HKEY_CLASSES_ROOT, "Word.Application\\CurVer"
                ):
                    return True
            except OSError:
                return False
        if system == "Darwin":
            return os.path.exists("/Applications/Microsoft Word.app")
    except Exception:  # pragma: no cover
        logger.exception("Word 安装检测失败")
        return False
    return False


def convert_docx_to_pdf(docx_path: str) -> str:
    """将 .docx 转换为 PDF，返回 PDF 路径（与 Word 同目录、同名，PRD 3.2.6）。

    Raises:
        PdfConversionError: 转换失败，附带面向用户的原因与解决建议
    """
    docx_path = str(Path(docx_path).resolve())
    if not Path(docx_path).exists():
        raise PdfConversionError(f"找不到 Word 文件：{docx_path}")

    if not is_word_available():
        raise PdfConversionError(
            "PDF 转换需要安装 Microsoft Word 或 WPS，请安装后重试。"
            "Word 文件已正常生成，可直接使用。"
        )

    try:
        import docx2pdf  # 延迟导入：无 Word 环境下其余功能不受影响
    except ImportError as exc:
        raise PdfConversionError(
            "PDF 转换组件缺失（docx2pdf 未安装）。Word 文件已正常生成。"
        ) from exc

    # Windows COM 线程初始化：PDF 转换通常在后台 QThread 中执行，
    # COM 需按线程初始化，否则 docx2pdf 调用 Word 自动化会失败
    com_initialized = False
    if platform.system() == "Windows":
        try:
            import pythoncom

            pythoncom.CoInitialize()
            com_initialized = True
        except ImportError:  # pywin32 未安装时交给 docx2pdf 自行处理
            pass

    try:
        docx2pdf.convert(docx_path)
    except Exception as exc:
        logger.exception("docx2pdf 转换失败：%s", docx_path)
        raise PdfConversionError(
            "PDF 转换失败："
            f"{_friendly_cause(exc)}。"
            "请确认 Word/WPS 可以正常打开该文件。Word 文件已正常生成，可直接使用。"
        ) from exc
    finally:
        if com_initialized:
            try:
                pythoncom.CoUninitialize()
            except Exception:  # pragma: no cover - 清理失败不影响结果
                pass

    pdf_path = str(Path(docx_path).with_suffix(".pdf"))
    if not Path(pdf_path).exists():
        raise PdfConversionError(
            "PDF 转换失败：未生成 PDF 文件。Word 文件已正常生成，可直接使用。"
        )
    return pdf_path


def _friendly_cause(exc: Exception) -> str:
    """将底层异常映射为用户可读的简短原因。"""
    text = f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    if "timed out" in lowered or "timeout" in lowered:
        return "调用 Word 超时"
    if "permission" in lowered:
        return "没有写入文件的权限，或该文件正在被 Word 打开"
    return "Word 自动化调用出错"


def open_file_in_system(path: str) -> None:
    """用系统默认程序打开文件（预览 / 打开历史产物用）。"""
    path = str(path)
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.Popen(["open", path])
        else:
            opener = shutil.which("xdg-open")
            if opener:
                subprocess.Popen([opener, path])
    except Exception:
        logger.exception("打开文件失败：%s", path)
