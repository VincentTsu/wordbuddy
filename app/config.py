"""
WordBuddy 配置管理
负责加载、保存 config.json，提供配置读写接口
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

from app.constants import DEFAULT_CONFIG, CONFIG_FILENAME


def get_app_data_dir() -> Path:
    """获取应用数据目录（跨平台）"""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    
    app_dir = base / "WordBuddy"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_config_path() -> Path:
    return get_app_data_dir() / CONFIG_FILENAME


def get_db_path() -> Path:
    from app.constants import DB_FILENAME
    return get_app_data_dir() / DB_FILENAME


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个字典，override 的值覆盖 base"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Config:
    _instance = None
    _data: Dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def load(self):
        """从文件加载配置，与默认值合并"""
        config_path = get_config_path()
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._data = _deep_merge(DEFAULT_CONFIG, saved)
            except Exception:
                self._data = DEFAULT_CONFIG.copy()
        else:
            self._data = DEFAULT_CONFIG.copy()
        self._loaded = True

    def save(self):
        """保存配置到文件"""
        config_path = get_config_path()
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def get(self, *keys, default=None):
        """多级 key 访问，例如 config.get('llm', 'api_key')"""
        data = self._data
        for key in keys:
            if isinstance(data, dict) and key in data:
                data = data[key]
            else:
                return default
        return data

    def set(self, *keys_and_value):
        """设置多级 key 的值，最后一个参数为值"""
        if len(keys_and_value) < 2:
            raise ValueError("至少需要一个 key 和一个 value")
        keys = keys_and_value[:-1]
        value = keys_and_value[-1]
        data = self._data
        for key in keys[:-1]:
            if key not in data or not isinstance(data[key], dict):
                data[key] = {}
            data = data[key]
        data[keys[-1]] = value

    def is_llm_configured(self) -> bool:
        return bool(self.get("llm", "api_key"))

    def is_cos_configured(self) -> bool:
        cos = self._data.get("cos", {})
        return all([cos.get("secret_id"), cos.get("secret_key"), cos.get("bucket")])

    @property
    def llm_base_url(self) -> str:
        return self.get("llm", "base_url", default="https://api.deepseek.com/v1")

    @property
    def llm_api_key(self) -> str:
        return self.get("llm", "api_key", default="")

    @property
    def llm_model(self) -> str:
        return self.get("llm", "model", default="deepseek-chat")

    @property
    def cos_secret_id(self) -> str:
        return self.get("cos", "secret_id", default="")

    @property
    def cos_secret_key(self) -> str:
        return self.get("cos", "secret_key", default="")

    @property
    def cos_bucket(self) -> str:
        return self.get("cos", "bucket", default="")

    @property
    def cos_region(self) -> str:
        return self.get("cos", "region", default="ap-guangzhou")

    @property
    def review_interval_minutes(self) -> int:
        return self.get("settings", "review_interval_minutes", default=30)

    @property
    def fill_ratio(self) -> int:
        return self.get("settings", "fill_ratio", default=25)


# 全局单例
config = Config()
