"""配置管理模块（PRD 3.2.7 / 4.2）。

职责：
- API Key 的本地加密存储（cryptography Fernet 对称加密）
- 用户偏好设置（模型、Base URL、导出目录、导出格式）的持久化
- 应用数据目录管理

安全说明：
    API Key 不以明文落盘。加密密钥与密文均保存在用户主目录的
    ~/.resume_optimizer/ 下，不随项目分发、不上传任何服务器，
    仅当前操作系统用户可访问，与 PRD 中 DPAPI 的
    "仅当前用户可解密"目标一致（跨平台统一使用 Fernet 实现）。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

APP_DIR = Path.home() / ".resume_optimizer"
SECRET_FILE = APP_DIR / "secret.key"
CONFIG_FILE = APP_DIR / "config.json"
DB_FILE = APP_DIR / "history.db"

#: 模型映射表（PRD 4.3），key 为 API model 名，value 为界面展示名
AVAILABLE_MODELS = {
    "deepseek-v4-pro": "DeepSeek-V4-Pro（最强中文理解，默认）",
    "deepseek-flash": "DeepSeek-V4.1-Flash（更快、更便宜）",
}

#: 各模型输出上限（PRD 4.3：V4-Pro 最大输出 384K，Flash 上限较低）。
#: LLM 客户端按此表对 max_tokens 封顶，防止请求超过模型实际能力被 API 拒绝。
MODEL_MAX_OUTPUT_TOKENS = {
    "deepseek-v4-pro": 32768,
    "deepseek-flash": 16384,
}
DEFAULT_MAX_OUTPUT_TOKENS = 16384

DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_BASE_URL = "https://api.deepseek.com"

#: 改写尺度三档（PRD 3.2.3）
REWRITE_LEVELS = {
    "conservative": "保守",
    "moderate": "中度",
    "deep": "深度",
}

_lock = threading.Lock()


def ensure_app_dir() -> Path:
    """确保应用数据目录存在，返回其路径。"""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    return APP_DIR


def default_export_dir() -> str:
    """默认导出目录：用户"文档"目录下的 ResumeOpt（PRD 3.2.5）。"""
    return str(Path.home() / "Documents" / "ResumeOpt")


# ---------------------------------------------------------------------------
# Fernet 密钥管理
# ---------------------------------------------------------------------------

def _get_fernet() -> Fernet:
    """加载（或首次生成）本机加密密钥，返回 Fernet 实例。

    密钥文件不存在时生成新密钥并写入；存在则直接加载。
    加密密钥丢失会导致已存 API Key 无法解密，调用方需处理 InvalidToken。
    """
    with _lock:
        ensure_app_dir()
        if SECRET_FILE.exists():
            key = SECRET_FILE.read_bytes().strip()
        else:
            key = Fernet.generate_key()
            SECRET_FILE.write_bytes(key)
            try:
                SECRET_FILE.chmod(0o600)
            except OSError:
                pass
        return Fernet(key)


# ---------------------------------------------------------------------------
# API Key 存取
# ---------------------------------------------------------------------------

def save_api_key(api_key: str) -> None:
    """加密保存 API Key。"""
    api_key = api_key.strip()
    if not api_key:
        raise ValueError("API Key 不能为空")
    f = _get_fernet()
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = _read_config()
    data["api_key_encrypted"] = f.encrypt(api_key.encode("utf-8")).decode("ascii")
    _write_config(data)


def load_api_key() -> str:
    """读取并解密 API Key；未配置或解密失败返回空字符串。"""
    data = _read_config()
    encrypted = data.get("api_key_encrypted", "")
    if not encrypted:
        return ""
    try:
        return _get_fernet().decrypt(encrypted.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        # 密钥文件被更换/损坏，视为未配置
        return ""


def has_api_key() -> bool:
    """是否已配置 API Key（用于首次启动引导判断）。"""
    return bool(load_api_key())


def clear_api_key() -> None:
    """清除已保存的 API Key。"""
    data = _read_config()
    data.pop("api_key_encrypted", None)
    _write_config(data)


# ---------------------------------------------------------------------------
# 用户设置
# ---------------------------------------------------------------------------

_SETTINGS_DEFAULTS = {
    "model": DEFAULT_MODEL,
    "base_url": DEFAULT_BASE_URL,
    "export_dir": default_export_dir(),
    "export_word": True,
    "export_pdf": True,
}


def get_settings() -> dict:
    """读取用户设置，缺省项回填默认值。"""
    data = _read_config()
    settings = dict(_SETTINGS_DEFAULTS)
    settings.update({k: v for k, v in data.get("settings", {}).items() if k in settings})
    return settings


def update_settings(**kwargs) -> None:
    """更新（部分）用户设置。"""
    with _lock:
        data = _read_config()
        settings = data.get("settings", {})
        for key, value in kwargs.items():
            if key in _SETTINGS_DEFAULTS:
                settings[key] = value
        data["settings"] = settings
        _write_config(data)


# ---------------------------------------------------------------------------
# 内部读写
# ---------------------------------------------------------------------------

def _read_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # 配置损坏时不让程序崩溃，视为空配置
        return {}


def _write_config(data: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
