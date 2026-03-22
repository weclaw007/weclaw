"""
模型注册表：统一管理所有厂商大模型 + 本地 Ollama 模型

功能：
- 从 models.yaml 加载模型配置
- 自动发现本地 Ollama 已安装的模型
- 提供统一的工厂方法创建 LLM 实例
- 支持运行时查询所有可用模型
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

# 各 provider 需要的 langchain 集成包映射
_PROVIDER_PACKAGES: dict[str, str] = {
    "openai": "langchain-openai",
    "anthropic": "langchain-anthropic",
    "google_genai": "langchain-google-genai",
    "ollama": "langchain-ollama",
}


@dataclass
class ModelConfig:
    """单个模型的配置"""
    name: str                           # 配置名（如 "qwen-plus"）
    provider: str                       # langchain provider（如 "openai", "anthropic", "google_genai", "ollama"）
    model: str                          # 实际模型名
    base_url: str | None = None         # API 地址（可选）
    api_key_env: str | None = None      # 环境变量名，运行时从 os.getenv() 读取
    extra_kwargs: dict[str, Any] = field(default_factory=dict)  # 其他透传参数

    @property
    def display_name(self) -> str:
        """用于 UI 显示的名称"""
        return self.name

    @property
    def is_ollama(self) -> bool:
        """是否为 Ollama 本地模型"""
        return self.provider == "ollama"


class ModelRegistry:
    """
    模型注册表：管理所有可用模型配置。

    用法示例::

        registry = ModelRegistry()
        # 或使用单例
        registry = ModelRegistry.get_instance()

        # 列出所有可用模型
        print(registry.list_available())

        # 创建默认模型
        llm = registry.create_chat_model()

        # 创建指定模型
        llm = registry.create_chat_model("gpt-4o")
    """

    _instance: "ModelRegistry | None" = None

    def __init__(self, config_path: str | Path | None = None) -> None:
        self._models: dict[str, ModelConfig] = {}
        self._default: str = ""
        self._summary_model: str = ""
        self._multimodal_model: str = ""
        self._ollama_host: str = DEFAULT_OLLAMA_HOST
        self._auto_discover_ollama_enabled: bool = True

        # 查找配置文件
        if config_path is None:
            # 默认在项目根目录查找 models.yaml
            config_path = self._find_config()

        if config_path and Path(config_path).exists():
            self._load_config(Path(config_path))
        else:
            logger.warning(f"模型配置文件未找到: {config_path}，将仅使用 Ollama 自动发现")

        # 自动发现本地 Ollama 模型
        if self._auto_discover_ollama_enabled:
            self._auto_discover_ollama()

    @classmethod
    def get_instance(cls, config_path: str | Path | None = None) -> "ModelRegistry":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls(config_path)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（主要用于测试）"""
        cls._instance = None

    @staticmethod
    def _find_config() -> Path | None:
        """从当前文件向上查找 models.yaml"""
        # 优先查找项目根目录（包含 .env 的目录）
        current = Path(__file__).resolve().parent
        for _ in range(10):  # 最多向上 10 层
            candidate = current / "models.yaml"
            if candidate.exists():
                return candidate
            # 也检查是否到了项目根目录
            if (current / ".env").exists() or (current / "pyproject.toml").exists():
                candidate = current / "models.yaml"
                return candidate if candidate.exists() else None
            parent = current.parent
            if parent == current:
                break
            current = parent
        return None

    def _load_config(self, path: Path) -> None:
        """从 YAML 文件加载模型配置"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not data or not isinstance(data, dict):
                logger.warning(f"配置文件为空或格式错误: {path}")
                return

            # 加载模型列表
            models = data.get("models", {})
            for name, config in models.items():
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

            # 加载默认模型
            self._default = data.get("default", "")

            # 加载摘要模型
            self._summary_model = data.get("summary_model", "")

            # 加载多模态预处理模型
            self._multimodal_model = data.get("multimodal_model", "")

            # 加载 Ollama 配置
            ollama_config = data.get("ollama", {})
            if isinstance(ollama_config, dict):
                self._ollama_host = ollama_config.get("host", DEFAULT_OLLAMA_HOST)
                self._auto_discover_ollama_enabled = ollama_config.get("auto_discover", True)

            logger.info(f"从 {path} 加载了 {len(self._models)} 个模型配置，默认模型: {self._default}")

        except Exception as e:
            logger.error(f"加载模型配置文件失败: {e}")

    def _auto_discover_ollama(self) -> None:
        """利用 OllamaProvider 自动发现并注册本地 Ollama 模型"""
        try:
            provider = OllamaProvider(host=self._ollama_host)
            if not provider.is_installed():
                logger.debug("Ollama 未安装，跳过自动发现")
                return
            if not provider.is_running():
                logger.debug("Ollama 服务未运行，跳过自动发现")
                return

            models = provider.list_models()
            discovered_count = 0
            for m in models:
                # 用 "ollama/" 前缀区分自动发现的模型
                key = f"ollama/{m.name}"
                if key not in self._models:
                    self._models[key] = ModelConfig(
                        name=key,
                        provider="ollama",
                        model=m.name,
                        base_url=self._ollama_host,
                        api_key_env=None,
                    )
                    discovered_count += 1

            if discovered_count:
                discovered_names = [f"ollama/{m.name}" for m in models if f"ollama/{m.name}" in self._models]
                logger.info(f"自动发现 {discovered_count} 个 Ollama 本地模型: {', '.join(discovered_names)}")

        except Exception as e:
            logger.warning(f"自动发现 Ollama 模型失败: {e}")

    def create_chat_model(
        self,
        name: str | None = None,
        **overrides: Any,
    ) -> Any:
        """
        根据配置名创建 LLM 实例。

        Args:
            name: 模型配置名。None 则使用默认模型。
            **overrides: 透传给 init_chat_model 的额外参数（会覆盖配置文件中的值）

        Returns:
            langchain BaseChatModel 实例

        Raises:
            ValueError: 模型配置不存在
            ImportError: 缺少对应的 langchain 集成包
        """
        resolved_name = name or self._default
        if not resolved_name:
            raise ValueError("未指定模型名且未配置默认模型，请在 models.yaml 中设置 default 字段")

        config = self._models.get(resolved_name)
        if config is None:
            available = ", ".join(sorted(self._models.keys()))
            raise ValueError(f"模型 '{resolved_name}' 不存在。可用模型: {available}")

        # 检查依赖包是否安装
        self._check_provider_package(config.provider)

        # 构建参数
        kwargs: dict[str, Any] = {**config.extra_kwargs, **overrides}

        if config.base_url:
            kwargs["base_url"] = config.base_url

        # 从环境变量读取 API Key
        if config.api_key_env:
            api_key = os.getenv(config.api_key_env)
            if not api_key:
                logger.warning(
                    f"环境变量 {config.api_key_env} 未设置，模型 '{resolved_name}' 可能无法正常工作。"
                    f"请在 .env 文件中配置。"
                )
            else:
                kwargs["api_key"] = api_key

        logger.info(f"创建模型: {resolved_name} (provider={config.provider}, model={config.model})")

        return init_chat_model(
            model=config.model,
            model_provider=config.provider,
            **kwargs,
        )

    @staticmethod
    def _check_provider_package(provider: str) -> None:
        """检查对应 provider 的 langchain 集成包是否已安装"""
        package = _PROVIDER_PACKAGES.get(provider)
        if not package:
            return  # 未知 provider，跳过检查

        # 将包名转换为 import 名（langchain-openai -> langchain_openai）
        import_name = package.replace("-", "_")
        try:
            __import__(import_name)
        except ImportError:
            raise ImportError(
                f"使用 provider '{provider}' 需要安装 {package}，"
                f"请执行: pip install {package}"
            )

    def list_available(self) -> list[str]:
        """列出所有可用模型配置名"""
        return sorted(self._models.keys())

    def list_cloud_models(self) -> list[str]:
        """列出所有云端模型（非 Ollama）"""
        return sorted(k for k, v in self._models.items() if not v.is_ollama)

    def list_ollama_models(self) -> list[str]:
        """列出所有 Ollama 本地模型"""
        return sorted(k for k, v in self._models.items() if v.is_ollama)

    def get_model_config(self, name: str) -> ModelConfig | None:
        """获取指定模型的配置"""
        return self._models.get(name)

    def get_default(self) -> str:
        """获取默认模型名"""
        return self._default

    def get_summary_model(self) -> str:
        """获取摘要模型名，未配置时回退到默认模型"""
        return self._summary_model or self._default

    def get_multimodal_model(self) -> str:
        """获取多模态预处理模型名，未配置时回退到默认模型"""
        return self._multimodal_model or self._default

    def has_model(self, name: str) -> bool:
        """检查模型是否存在"""
        return name in self._models

    def refresh_ollama(self) -> None:
        """重新扫描 Ollama 本地模型（用于运行时刷新）"""
        # 移除旧的自动发现模型
        to_remove = [k for k, v in self._models.items() if k.startswith("ollama/")]
        for k in to_remove:
            del self._models[k]
        # 重新发现
        self._auto_discover_ollama()

    def get_grouped_models(self) -> dict[str, list[str]]:
        """
        按 provider 分组返回模型列表，用于 UI 显示。

        Returns:
            {"OpenAI 兼容": ["qwen-plus", ...], "Anthropic": [...], "Ollama 本地": [...]}
        """
        groups: dict[str, list[str]] = {}

        # provider 显示名映射
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

    def print_available(self) -> None:
        """打印所有可用模型（调试用）"""
        groups = self.get_grouped_models()
        print("=" * 50)
        print("  可用模型列表")
        print("=" * 50)
        for group_name, model_names in groups.items():
            print(f"\n  📦 {group_name}:")
            for name in model_names:
                config = self._models[name]
                default_mark = " ⭐" if name == self._default else ""
                print(f"    - {name} ({config.model}){default_mark}")
        print()
