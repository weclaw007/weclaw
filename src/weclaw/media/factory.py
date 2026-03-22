"""
媒体处理器工厂。

根据配置创建对应的 BaseMediaProcessor 实例。
"""

import logging
import os
from typing import Any, Dict, Type

from weclaw.media.base import BaseMediaProcessor

logger = logging.getLogger(__name__)


class MediaProcessorFactory:
    """媒体处理器工厂

    使用方式:
        # 方式 1：直接指定类型
        processor = MediaProcessorFactory.create("openai_api", model_name="qwen-vl")

        # 方式 2：从配置字典创建
        processor = MediaProcessorFactory.create_from_config({
            "type": "dashscope_sdk",
            "image_model": "qwen-vl-max",
            "audio_model": "paraformer-v2",
        })

        # 方式 3：注册自定义处理器
        MediaProcessorFactory.register("my_sdk", MySDKProcessor)
        processor = MediaProcessorFactory.create("my_sdk")
    """

    # 自定义处理器注册表
    _registry: Dict[str, Type[BaseMediaProcessor]] = {}

    @classmethod
    def register(cls, name: str, processor_class: Type[BaseMediaProcessor]):
        """注册自定义处理器类型

        Args:
            name: 处理器类型名称
            processor_class: 处理器类（必须继承 BaseMediaProcessor）
        """
        cls._registry[name] = processor_class
        logger.debug(f"已注册媒体处理器: {name}")

    @classmethod
    def create(
        cls,
        processor_type: str = "openai_api",
        model_name: str | None = None,
        api_key: str | None = None,
        config: Dict[str, Any] | None = None,
    ) -> BaseMediaProcessor:
        """创建媒体处理器实例

        Args:
            processor_type: 处理器类型
                - "openai_api": OpenAI 兼容协议
                - "dashscope_sdk": 阿里云 DashScope SDK
                - 其他已注册的自定义类型
            model_name: 模型名称（用于 openai_api 类型）
            api_key: API Key（可选）
            config: 额外配置

        Returns:
            BaseMediaProcessor 实例

        Raises:
            ValueError: 不支持的处理器类型
        """
        config = config or {}

        if processor_type == "openai_api":
            from weclaw.media.processors.openai_processor import OpenAIProcessor
            return OpenAIProcessor(model_name=model_name, config=config)

        elif processor_type == "dashscope_sdk":
            from weclaw.media.processors.dashscope_processor import DashScopeProcessor
            key = api_key or os.getenv("DASHSCOPE_API_KEY")
            return DashScopeProcessor(api_key=key, config=config)

        elif processor_type in cls._registry:
            return cls._registry[processor_type](config=config)

        else:
            raise ValueError(
                f"不支持的处理器类型: {processor_type}，"
                f"可选: openai_api, dashscope_sdk, {', '.join(cls._registry.keys())}"
            )

    @classmethod
    def create_from_config(cls, config: Dict[str, Any]) -> BaseMediaProcessor:
        """从配置字典创建处理器

        配置格式示例:
            {
                "type": "openai_api",
                "model": "qwen-vl",
                "request_timeout": 120,
            }
            或
            {
                "type": "dashscope_sdk",
                "api_key_env": "DASHSCOPE_API_KEY",
                "image_model": "qwen-vl-max",
                "audio_model": "paraformer-v2",
            }

        Args:
            config: 配置字典

        Returns:
            BaseMediaProcessor 实例
        """
        processor_type = config.get("type", "openai_api")

        # 读取 API Key
        api_key = None
        if api_key_env := config.get("api_key_env"):
            api_key = os.getenv(api_key_env)

        # 提取处理器专用配置（排除公共字段）
        _public_keys = {"type", "model", "api_key_env"}
        processor_config = {
            k: v for k, v in config.items() if k not in _public_keys
        }

        return cls.create(
            processor_type=processor_type,
            model_name=config.get("model"),
            api_key=api_key,
            config=processor_config,
        )
