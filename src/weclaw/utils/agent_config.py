"""Agent 配置管理 - 使用 TOML 文件保存 agent 的各项配置。

配置文件位于 ~/.weclaw/sessions/<session_id>/agent.toml，每个 agent 独立配置。
支持：
- persona: agent 人格设置（系统提示词中的角色描述）
- 后续可扩展其他配置项
"""

import logging
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # fallback

from weclaw.utils.paths import get_session_dir

logger = logging.getLogger(__name__)

# 配置文件名
CONFIG_FILENAME = "agent.toml"

# 默认配置
DEFAULT_CONFIG = {
    "persona": "",  # 人格设置，为空表示不启用
    "job_alert": {
        "enabled": True,       # 是否启用定时任务到期预警
        "check_interval": 600, # 巡检间隔（秒），默认 10 分钟
        "ahead_seconds": 900,  # 提前预警时间（秒），默认 15 分钟
    },
}


def _get_config_path(session_id: str = "main") -> Path:
    """获取配置文件路径：~/.weclaw/sessions/<session_id>/agent.toml"""
    return get_session_dir(session_id) / CONFIG_FILENAME


def _serialize_toml(data: dict) -> str:
    """将字典序列化为 TOML 格式字符串。

    仅支持简单的 key=value 和 [section] 格式，满足当前需求。
    """
    lines = []
    # 先输出顶层简单值
    top_keys = []
    section_keys = []
    for k, v in data.items():
        if isinstance(v, dict):
            section_keys.append(k)
        else:
            top_keys.append(k)

    for k in top_keys:
        v = data[k]
        lines.append(f"{k} = {_format_toml_value(v)}")

    for k in section_keys:
        lines.append("")
        lines.append(f"[{k}]")
        for sk, sv in data[k].items():
            lines.append(f"{sk} = {_format_toml_value(sv)}")

    return "\n".join(lines) + "\n"


def _format_toml_value(value) -> str:
    """将单个值格式化为 TOML 值字符串。"""
    if isinstance(value, str):
        # 多行字符串使用 TOML 多行基本字符串
        if "\n" in value:
            return f'"""\n{value}"""'
        # 单行字符串
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    elif isinstance(value, bool):
        return "true" if value else "false"
    elif isinstance(value, int):
        return str(value)
    elif isinstance(value, float):
        return str(value)
    elif isinstance(value, list):
        items = ", ".join(_format_toml_value(item) for item in value)
        return f"[{items}]"
    else:
        return f'"{value}"'


class AgentConfig:
    """Agent 配置管理器。

    提供对 agent.toml 的读写操作，支持人格设置和通用配置。

    用法:
        config = AgentConfig(session_id="my_session")
        # 获取人格设置
        persona = config.persona
        # 设置人格
        config.persona = "你是一个友好的助手"
        config.save()

        # 通用 get/set
        value = config.get("some_key", default="")
        config.set("some_key", "some_value")
        config.save()
    """

    def __init__(self, session_id: str = "main"):
        self._config: dict = {}
        self._session_id = session_id
        self._path = _get_config_path(session_id)
        self.load()

    def load(self) -> None:
        """从文件加载配置。文件不存在或解析失败时使用默认配置。"""
        if self._path.exists():
            try:
                raw = self._path.read_text(encoding="utf-8")
                self._config = tomllib.loads(raw)
                logger.debug(f"已加载配置: {self._path}")
            except Exception as e:
                logger.warning(f"加载配置文件失败，使用默认配置: {e}")
                self._config = dict(DEFAULT_CONFIG)
        else:
            self._config = dict(DEFAULT_CONFIG)

    def save(self) -> None:
        """将当前配置保存到文件。"""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(_serialize_toml(self._config), encoding="utf-8")
            logger.info(f"配置已保存: {self._path}")
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            raise

    # ── 人格设置 ──

    @property
    def persona(self) -> str:
        """获取人格设置。"""
        return self._config.get("persona", "")

    @persona.setter
    def persona(self, value: str) -> None:
        """设置人格并自动保存。"""
        self._config["persona"] = value
        self.save()

    # ── 定时任务预警配置 ──

    @property
    def job_alert_enabled(self) -> bool:
        """是否启用定时任务到期预警。"""
        alert = self._config.get("job_alert", {})
        return alert.get("enabled", True)

    @property
    def job_alert_check_interval(self) -> int:
        """巡检间隔秒数。"""
        alert = self._config.get("job_alert", {})
        return alert.get("check_interval", 600)

    @property
    def job_alert_ahead_seconds(self) -> int:
        """提前预警秒数。"""
        alert = self._config.get("job_alert", {})
        return alert.get("ahead_seconds", 900)

    # ── 通用 get/set ──

    def get(self, key: str, default=None):
        """获取配置值，支持点号分隔的嵌套路径（如 'section.key'）。"""
        keys = key.split(".")
        obj = self._config
        for k in keys:
            if isinstance(obj, dict) and k in obj:
                obj = obj[k]
            else:
                return default
        return obj

    def set(self, key: str, value) -> None:
        """设置配置值，支持点号分隔的嵌套路径（如 'section.key'）。

        设置后需要手动调用 save() 持久化。
        """
        keys = key.split(".")
        obj = self._config
        for k in keys[:-1]:
            if k not in obj or not isinstance(obj[k], dict):
                obj[k] = {}
            obj = obj[k]
        obj[keys[-1]] = value

    def to_dict(self) -> dict:
        """返回配置字典的副本。"""
        return dict(self._config)
