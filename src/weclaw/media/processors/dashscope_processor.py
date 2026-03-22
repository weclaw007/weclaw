"""
阿里云 DashScope SDK 媒体处理器。

直接使用 DashScope SDK 处理媒体内容，绕过 OpenAI 协议限制。
支持：
  - qwen-vl 系列：图片 / 视频理解
  - paraformer 系列：语音识别（ASR）
  - qwen-audio 系列：音频理解
"""

import logging
from typing import Any, Dict

from weclaw.media.base import (
    BaseMediaProcessor,
    MediaInput,
    MediaResult,
)

logger = logging.getLogger(__name__)


class DashScopeProcessor(BaseMediaProcessor):
    """阿里云 DashScope SDK 媒体处理器

    Config 支持的参数:
        api_key: str           - API Key（可选，默认从 DASHSCOPE_API_KEY 环境变量读取）
        image_model: str       - 图片/视频理解模型，默认 qwen-vl-max
        audio_model: str       - 语音识别模型，默认 paraformer-v2
    """

    def __init__(
        self,
        api_key: str | None = None,
        config: Dict[str, Any] | None = None,
    ):
        super().__init__(config)
        self.api_key = api_key
        self.image_model = self.config.get("image_model", "qwen-vl-max")
        self.audio_model = self.config.get("audio_model", "paraformer-v2")

    async def process(self, input_data: MediaInput) -> MediaResult:
        """处理媒体输入

        根据媒体类型分发：
        - 纯音频 → _process_audio()  使用 paraformer ASR
        - 图片/视频/混合 → _process_multimodal()  使用 qwen-vl

        Args:
            input_data: 统一的媒体输入

        Returns:
            MediaResult 处理结果
        """
        if not input_data.has_media():
            return MediaResult(text=input_data.text, media_type="text")

        media_types = input_data.get_media_types()

        # 纯音频：走语音识别
        if media_types == ["audio"]:
            return await self._process_audio(input_data)

        # 图片/视频/混合：走多模态模型
        return await self._process_multimodal(input_data)

    # ── 私有方法 ─────────────────────────────────────────────

    def _init_sdk(self):
        """延迟初始化 DashScope SDK（首次调用时导入）"""
        # TODO: 实现
        raise NotImplementedError

    async def _process_audio(self, input_data: MediaInput) -> MediaResult:
        """使用 paraformer 进行语音识别

        Args:
            input_data: 包含音频的输入

        Returns:
            MediaResult（text 为转录文本）
        """
        # TODO: 实现
        raise NotImplementedError

    async def _process_multimodal(self, input_data: MediaInput) -> MediaResult:
        """使用 qwen-vl 处理图片/视频/混合媒体

        Args:
            input_data: 包含图片/视频的输入

        Returns:
            MediaResult（text 为内容描述）
        """
        # TODO: 实现
        raise NotImplementedError
