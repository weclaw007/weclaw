"""Agent 配置管理 - 使用 TOML 文件保存 agent 的各项配置。

配置文件位于 ~/.weclaw/sessions/<session_id>/agent.toml，每个 agent 独立配置。
"""

import copy
import logging
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # fallback

from weclaw.utils.paths import get_session_dir

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "agent.toml"

DEFAULT_CONFIG = {
    "persona": "",
    "job_alert": {
        "enabled": True,
        "check_interval": 600,
        "ahead_seconds": 900,
    },
}


def _get_config_path(session_id: str = "main") -> Path:
    return get_session_dir(session_id) / CONFIG_FILENAME


def _format_toml_value(value) -> str:
    """将单个值格式化为 TOML 值字符串。"""
    if isinstance(value, str):
        if "\n" in value:
            return f'"""\n{value}"""'
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    elif isinstance(value, bool):
        return "true" if value else "false"
    elif isinstance(value, (int, float)):
        return str(value)
    elif isinstance(value, list):
        items = ", ".join(_format_toml_value(item) for item in value)
        return f"[{items}]"
    else:
        return f'"{value}"'


def _serialize_toml(data: dict) -> str:
    """将字典序列化为 TOML 格式字符串。"""
    lines = []
    top_keys = [k for k, v in data.items() if not isinstance(v, dict)]
    section_keys = [k for k, v in data.items() if isinstance(v, dict)]

    for k in top_keys:
        lines.append(f"{k} = {_format_toml_value(data[k])}")
    for k in section_keys:
        lines.append("")
        lines.append(f"[{k}]")
        for sk, sv in data[k].items():
            lines.append(f"{sk} = {_format_toml_value(sv)}")

    return "\n".join(lines) + "\n"


class AgentConfig:
    """Agent 配置管理器 - 读写 agent.toml"""

    def __init__(self, session_id: str = "main"):
        self._config: dict = {}
        self._session_id = session_id
        self._path = _get_config_path(session_id)
        self.load()

    def load(self) -> None:
        if self._path.exists():
            try:
                raw = self._path.read_text(encoding="utf-8")
                self._config = tomllib.loads(raw)
            except Exception as e:
                logger.warning(f"加载配置文件失败，使用默认配置: {e}")
                self._config = copy.deepcopy(DEFAULT_CONFIG)
        else:
            self._config = copy.deepcopy(DEFAULT_CONFIG)

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(_serialize_toml(self._config), encoding="utf-8")
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            raise

    # ── 人格设置 ──

    @property
    def persona(self) -> str:
        return self._config.get("persona", "")

    @persona.setter
    def persona(self, value: str) -> None:
        self._config["persona"] = value
        self.save()

    # ── 定时任务预警配置 ──

    @property
    def job_alert_enabled(self) -> bool:
        return self._config.get("job_alert", {}).get("enabled", True)

    @property
    def job_alert_check_interval(self) -> int:
        return self._config.get("job_alert", {}).get("check_interval", 600)

    @property
    def job_alert_ahead_seconds(self) -> int:
        return self._config.get("job_alert", {}).get("ahead_seconds", 900)

    # ── 通用 get/set ──

    def get(self, key: str, default=None):
        keys = key.split(".")
        obj = self._config
        for k in keys:
            if isinstance(obj, dict) and k in obj:
                obj = obj[k]
            else:
                return default
        return obj

    def set(self, key: str, value) -> None:
        keys = key.split(".")
        obj = self._config
        for k in keys[:-1]:
            if k not in obj or not isinstance(obj[k], dict):
                obj[k] = {}
            obj = obj[k]
        obj[keys[-1]] = value

    def to_dict(self) -> dict:
        return dict(self._config)
