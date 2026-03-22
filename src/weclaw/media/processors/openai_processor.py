"""
OpenAI 兼容协议媒体处理器。

通过 OpenAI 兼容的多模态接口处理媒体内容。
支持所有兼容 OpenAI 协议的模型，例如：
  - OpenAI GPT-4o
  - 阿里云 qwen-vl（通过 compatible-mode）
  - DeepSeek 多模态
  - 等
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage

from weclaw.media.base import (
    BaseMediaProcessor,
    MediaInput,
    MediaItem,
    MediaResult,
    base64_encode_file,
    format_result_text,
    guess_mime_type,
    normalize_audio_format,
)
from weclaw.media.prompts import AUDIO_PROMPT, IMAGE_PROMPT, MIXED_MEDIA_PROMPT, VIDEO_PROMPT
from weclaw.utils.model_registry import ModelRegistry

logger = logging.getLogger(__name__)


class OpenAIProcessor(BaseMediaProcessor):
    """OpenAI 兼容协议媒体处理器

    内部将 MediaInput 转换为 OpenAI 多模态 content 数组，
    通过 LangChain ChatModel 调用模型。

    Config 支持的参数:
        request_timeout: int - 请求超时（秒），默认 120
    """

    def __init__(
        self,
        model_name: str | None = None,
        config: Dict[str, Any] | None = None,
    ):
        super().__init__(config)
        self.model_name = model_name

    # ── 核心方法 ─────────────────────────────────────────────

    async def process(self, input_data: MediaInput) -> MediaResult:
        """处理媒体输入

        将 MediaInput 转换为 OpenAI 多模态 content 数组，调用模型并返回结果。

        Args:
            input_data: 统一的媒体输入

        Returns:
            MediaResult 处理结果
        """
        # 没有媒体，直接返回文本
        if not input_data.has_media():
            return MediaResult(text=input_data.text, media_type="text")

        media_types = input_data.get_media_types()
        media_type_str = "+".join(media_types)

        # 选择提示词
        prompt = self._select_prompt(media_types)

        # 如果用户附带了文本，追加到提示词中
        if input_data.text:
            prompt += (
                f'\n\nThe user also said: "{input_data.text}". '
                f"Take this into account in your response."
            )

        # 构建 OpenAI 多模态 content 数组
        content = self._build_content(input_data, prompt)
        if not content:
            return MediaResult(
                text=input_data.text,
                media_type=media_type_str,
                success=False,
                error="无法构建媒体内容，可能媒体文件不存在或格式不支持",
            )

        # 创建模型实例并调用
        try:
            registry = ModelRegistry.get_instance()
            # 如果未指定模型，使用配置中的多模态模型
            resolved_name = self.model_name or registry.get_multimodal_model()
            request_timeout = self.config.get("request_timeout", 120)

            llm = registry.create_chat_model(
                name=resolved_name,
                request_timeout=request_timeout,
            )

            logger.info(
                f"调用 OpenAI 兼容模型处理 {media_type_str} 媒体: "
                f"{resolved_name or 'default'}"
            )

            response = await llm.ainvoke([HumanMessage(content=content)])
            extracted_text = (
                response.content if hasattr(response, "content") else str(response)
            )

            logger.info(
                f"媒体处理完成，从 {media_type_str} 提取了 {len(extracted_text)} 个字符"
            )

            # 组合原始文本和提取的媒体文本
            final_text = format_result_text(
                original_text=input_data.text,
                extracted_text=extracted_text,
                media_type_str=media_type_str,
            )

            # 提取 token 用量元数据
            metadata = {}
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                metadata["usage"] = response.usage_metadata
            if hasattr(response, "response_metadata") and response.response_metadata:
                metadata["response"] = response.response_metadata

            return MediaResult(
                text=final_text,
                media_type=media_type_str,
                success=True,
                metadata=metadata,
            )

        except Exception as e:
            logger.exception(f"OpenAI 媒体处理失败: {e}")
            # 降级：返回原始文本 + 错误信息
            fallback = input_data.text or ""
            if fallback:
                fallback += "\n\n"
            fallback += f"[系统: {media_type_str} 媒体处理失败 - {e}]"

            return MediaResult(
                text=fallback,
                media_type=media_type_str,
                success=False,
                error=str(e),
            )

    # ── 私有方法：提示词选择 ──────────────────────────────────

    def _select_prompt(self, media_types: List[str]) -> str:
        """根据媒体类型选择合适的提示词"""
        if len(media_types) > 1:
            return MIXED_MEDIA_PROMPT
        if "audio" in media_types:
            return AUDIO_PROMPT
        if "video" in media_types:
            return VIDEO_PROMPT
        return IMAGE_PROMPT

    # ── 私有方法：构建 OpenAI 多模态 content ─────────────────

    def _build_content(
        self,
        input_data: MediaInput,
        prompt: str,
    ) -> List[Dict[str, Any]]:
        """构建 OpenAI 多模态 content 数组

        按照 OpenAI Chat Completions API 格式，将文本和媒体组装为 content 数组：
          [
            {"type": "text", "text": "..."},
            {"type": "image_url", "image_url": {"url": "data:..."}},
            {"type": "input_audio", "input_audio": {"data": "...", "format": "wav"}},
            {"type": "video_url", "video_url": {"url": "data:..."}},
          ]

        Args:
            input_data: 媒体输入
            prompt: 提示词文本

        Returns:
            OpenAI 格式的 content 数组，构建失败返回空列表
        """
        content: List[Dict[str, Any]] = []

        # 1. 文本提示词
        content.append({"type": "text", "text": prompt})

        # 2. 图片项
        for item in input_data.image:
            built = self._build_image_item(item)
            if built:
                content.append(built)

        # 3. 音频项
        for item in input_data.audio:
            built = self._build_audio_item(item)
            if built:
                content.append(built)

        # 4. 视频项
        for item in input_data.video:
            built = self._build_video_item(item)
            if built:
                content.append(built)

        # 如果只有文本提示词，没有任何媒体项，则构建失败
        if len(content) <= 1:
            logger.warning("未能构建任何媒体 content 项")
            return []

        return content

    def _build_image_item(self, item: MediaItem) -> Optional[Dict[str, Any]]:
        """将 MediaItem 转换为 OpenAI image_url content 项

        支持三种输入类型：
          - file: 本地文件路径，读取后转为 base64 data URI
          - url: 远程 URL，直接使用
          - base64: 已编码的 base64 数据，组装为 data URI

        Returns:
            {"type": "image_url", "image_url": {"url": "..."}} 或 None
        """
        try:
            if item.type == "url":
                url = item.data
            elif item.type == "file":
                path = Path(item.data)
                if not path.exists():
                    logger.warning(f"图片文件不存在: {item.data}")
                    return None
                mime = item.mime or guess_mime_type(path)
                b64 = base64_encode_file(path)
                url = f"data:{mime};base64,{b64}"
            elif item.type == "base64":
                mime = item.mime or "image/png"
                url = f"data:{mime};base64,{item.data}"
            else:
                logger.warning(f"不支持的图片类型: {item.type}")
                return None

            return {"type": "image_url", "image_url": {"url": url}}

        except Exception as e:
            logger.error(f"构建图片 content 项失败: {e}")
            return None

    def _build_audio_item(self, item: MediaItem) -> Optional[Dict[str, Any]]:
        """将 MediaItem 转换为 OpenAI input_audio content 项

        支持三种输入类型：
          - file: 本地文件路径，读取后转为 base64
          - url: 远程 URL（需先下载，暂不支持，直接跳过）
          - base64: 已编码的 base64 数据

        Returns:
            {"type": "input_audio", "input_audio": {"data": "...", "format": "wav"}} 或 None
        """
        try:
            if item.type == "file":
                path = Path(item.data)
                if not path.exists():
                    logger.warning(f"音频文件不存在: {item.data}")
                    return None
                fmt = item.format or path.suffix.lower().lstrip(".") or "wav"
                fmt = normalize_audio_format(fmt)
                b64_data = base64_encode_file(path)
            elif item.type == "base64":
                fmt = normalize_audio_format(item.format or "wav")
                b64_data = item.data
            elif item.type == "url":
                logger.warning("OpenAI 协议暂不支持直接传入音频 URL，请使用 file 或 base64 类型")
                return None
            else:
                logger.warning(f"不支持的音频类型: {item.type}")
                return None

            return {
                "type": "input_audio",
                "input_audio": {"data": b64_data, "format": fmt},
            }

        except Exception as e:
            logger.error(f"构建音频 content 项失败: {e}")
            return None

    def _build_video_item(self, item: MediaItem) -> Optional[Dict[str, Any]]:
        """将 MediaItem 转换为 OpenAI video_url content 项

        支持三种输入类型：
          - file: 本地文件路径，读取后转为 base64 data URI
          - url: 远程 URL，直接使用
          - base64: 已编码的 base64 数据，组装为 data URI

        Returns:
            {"type": "video_url", "video_url": {"url": "..."}} 或 None
        """
        try:
            if item.type == "url":
                url = item.data
            elif item.type == "file":
                path = Path(item.data)
                if not path.exists():
                    logger.warning(f"视频文件不存在: {item.data}")
                    return None
                mime = item.mime or guess_mime_type(path)
                b64 = base64_encode_file(path)
                url = f"data:{mime};base64,{b64}"
            elif item.type == "base64":
                mime = item.mime or "video/mp4"
                url = f"data:{mime};base64,{item.data}"
            else:
                logger.warning(f"不支持的视频类型: {item.type}")
                return None

            return {"type": "video_url", "video_url": {"url": url}}

        except Exception as e:
            logger.error(f"构建视频 content 项失败: {e}")
            return None
