"""模型注册表：统一管理所有厂商大模型 + 本地 Ollama 模型

功能：
- 从 models.yaml 加载模型配置
- 自动发现本地 Ollama 已安装的模型
- 提供统一的工厂方法创建 LLM 实例
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from langchain.chat_models import init_chat_model

from weclaw.utils.ollama_provider import OllamaProvider, DEFAULT_OLLAMA_HOST

logger = logging.getLogger(__name__)

_PROVIDER_PACKAGES: dict[str, str] = {
    "openai": "langchain-openai",
    "anthropic": "langchain-anthropic",
    "google_genai": "langchain-google-genai",
    "ollama": "langchain-ollama",
}


@dataclass
class ModelConfig:
    """单个模型的配置"""
    name: str
    provider: str
    model: str
    base_url: str | None = None
    api_key_env: str | None = None
    extra_kwargs: dict[str, Any] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return self.name

    @property
    def is_ollama(self) -> bool:
        return self.provider == "ollama"


class ModelRegistry:
    """模型注册表：管理所有可用模型配置。"""

    _instance: "ModelRegistry | None" = None

    def __init__(self, config_path: str | Path | None = None) -> None:
        self._models: dict[str, ModelConfig] = {}
        self._default: str = ""
        self._multimodal_models: dict[str, str] = {}
        self._ollama_host: str = DEFAULT_OLLAMA_HOST
        self._auto_discover_ollama_enabled: bool = True
        self._ollama_discovered: bool = False

        if config_path is None:
            config_path = self._find_config()
        if config_path and Path(config_path).exists():
            self._load_config(Path(config_path))
        else:
            logger.warning(f"模型配置文件未找到: {config_path}，将仅使用 Ollama 自动发现")

    @classmethod
    def get_instance(cls, config_path: str | Path | None = None) -> "ModelRegistry":
        if cls._instance is None:
            cls._instance = cls(config_path)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None

    @staticmethod
    def _find_config() -> Path | None:
        current = Path(__file__).resolve().parent
        for _ in range(10):
            candidate = current / "models.yaml"
            if candidate.exists():
                return candidate
            if (current / ".env").exists() or (current / "pyproject.toml").exists():
                candidate = current / "models.yaml"
                return candidate if candidate.exists() else None
            parent = current.parent
            if parent == current:
                break
            current = parent
        return None

    def _load_config(self, path: Path) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not data or not isinstance(data, dict):
                return

            for name, config in data.get("models", {}).items():
                if not isinstance(config, dict):
                    continue
                self._models[name] = ModelConfig(
                    name=name,
                    provider=config.get("provider", "openai"),
                    model=config.get("model", name),
                    base_url=config.get("base_url"),
                    api_key_env=config.get("api_key_env"),
                    extra_kwargs=config.get("extra_kwargs", {}),
                )

            self._default = data.get("default", "")

            mm_config = data.get("multimodal_model", {})
            if isinstance(mm_config, dict):
                self._multimodal_models = {k: v for k, v in mm_config.items() if isinstance(v, str)}

            ollama_config = data.get("ollama", {})
            if isinstance(ollama_config, dict):
                self._ollama_host = ollama_config.get("host", DEFAULT_OLLAMA_HOST)
                self._auto_discover_ollama_enabled = ollama_config.get("auto_discover", True)

            logger.info(f"从 {path} 加载了 {len(self._models)} 个模型配置，默认: {self._default}")
        except Exception as e:
            logger.error(f"加载模型配置文件失败: {e}")

    def _auto_discover_ollama(self) -> None:
        try:
            provider = OllamaProvider(host=self._ollama_host)
            if not provider.is_installed() or not provider.is_running():
                return
            models = provider.list_models()
            for m in models:
                key = f"ollama/{m.name}"
                if key not in self._models:
                    self._models[key] = ModelConfig(
                        name=key, provider="ollama", model=m.name,
                        base_url=self._ollama_host,
                    )
            logger.info(f"自动发现 {len(models)} 个 Ollama 本地模型")
        except Exception as e:
            logger.warning(f"自动发现 Ollama 模型失败: {e}")

    def _ensure_ollama_discovered(self) -> None:
        """延迟触发 Ollama 自动发现（首次访问模型列表时调用）。"""
        if self._ollama_discovered or not self._auto_discover_ollama_enabled:
            return
        self._ollama_discovered = True
        self._auto_discover_ollama()

    def create_chat_model(self, name: str | None = None, **overrides: Any) -> Any:
        """根据配置名创建 LLM 实例。"""
        self._ensure_ollama_discovered()
        resolved_name = name or self._default
        if not resolved_name:
            raise ValueError("未指定模型名且未配置默认模型")

        config = self._models.get(resolved_name)
        if config is None:
            available = ", ".join(sorted(self._models.keys()))
            raise ValueError(f"模型 '{resolved_name}' 不存在。可用: {available}")

        self._check_provider_package(config.provider)
        kwargs: dict[str, Any] = {**config.extra_kwargs, **overrides}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        if config.api_key_env:
            api_key = os.getenv(config.api_key_env)
            if api_key:
                kwargs["api_key"] = api_key
            else:
                logger.warning(f"环境变量 {config.api_key_env} 未设置")

        return init_chat_model(model=config.model, model_provider=config.provider, **kwargs)

    @staticmethod
    def _check_provider_package(provider: str) -> None:
        package = _PROVIDER_PACKAGES.get(provider)
        if not package:
            return
        import_name = package.replace("-", "_")
        try:
            __import__(import_name)
        except ImportError:
            raise ImportError(f"使用 provider '{provider}' 需要安装 {package}")

    def list_available(self) -> list[str]:
        self._ensure_ollama_discovered()
        return sorted(self._models.keys())

    def list_cloud_models(self) -> list[str]:
        return sorted(k for k, v in self._models.items() if not v.is_ollama)

    def list_ollama_models(self) -> list[str]:
        self._ensure_ollama_discovered()
        return sorted(k for k, v in self._models.items() if v.is_ollama)

    def get_model_config(self, name: str) -> ModelConfig | None:
        return self._models.get(name)

    def get_default(self) -> str:
        return self._default

    def get_multimodal_model(self, media_type: str | None = None) -> str:
        if media_type and media_type in self._multimodal_models:
            return self._multimodal_models[media_type]
        return self._multimodal_models.get("image", self._default)

    def has_model(self, name: str) -> bool:
        self._ensure_ollama_discovered()
        return name in self._models

    def refresh_ollama(self) -> None:
        to_remove = [k for k in self._models if k.startswith("ollama/")]
        for k in to_remove:
            del self._models[k]
        self._ollama_discovered = False
        self._auto_discover_ollama()
        self._ollama_discovered = True

    def get_grouped_models(self) -> dict[str, list[str]]:
        self._ensure_ollama_discovered()
        groups: dict[str, list[str]] = {}
        display_names = {
            "openai": "OpenAI 兼容",
            "anthropic": "Anthropic",
            "google_genai": "Google Gemini",
            "ollama": "Ollama 本地",
        }
        for name, config in sorted(self._models.items()):
            group = display_names.get(config.provider, config.provider)
            groups.setdefault(group, []).append(name)
        return groups
