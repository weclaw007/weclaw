"""媒体预处理模块：将音频、图片、视频等多媒体输入通过多模态模型转换为纯文本。

架构思路：
  前端消息（含媒体） → media_processor（多模态模型提取文本） → Agent（纯文本处理）

这样 Agent 只需要处理纯文本，上下文不会因 base64 数据而膨胀。
"""

import base64
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage

from weclaw.utils.model_registry import ModelRegistry

logger = logging.getLogger(__name__)

# ── 媒体类型对应的预处理 Prompt ──────────────────────────────

_AUDIO_PROMPT = (
    "You are a speech-to-text assistant. "
    "Please transcribe the audio content accurately into text. "
    "If the audio is in a non-English language, transcribe it in the original language. "
    "Output only the transcribed text, nothing else."
)

_IMAGE_PROMPT = (
    "You are an image analysis assistant. "
    "Please describe the content of this image in detail, including: "
    "1. Main subjects and objects visible in the image. "
    "2. Text or writing if any (transcribe it exactly). "
    "3. Scene, background, and overall context. "
    "4. Any notable details, colors, or patterns. "
    "Be thorough but concise. Output the description in the same language as any text found in the image, "
    "or in Chinese if no text is present."
)

_VIDEO_PROMPT = (
    "You are a video analysis assistant. "
    "Please describe the content of this video in detail, including: "
    "1. Main events and actions that occur. "
    "2. People, objects, and scenes visible. "
    "3. Any spoken words or text overlays (transcribe them). "
    "4. The overall narrative or purpose of the video. "
    "Be thorough but concise. Output the description in the same language as any speech found in the video, "
    "or in Chinese if no speech is present."
)


# ── 辅助函数 ────────────────────────────────────────────────

def _base64_encode(path: str | Path) -> str:
    """读取文件并返回 base64 文本。"""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _get_mime_type(path: str | Path) -> str:
    """根据扩展名推断 MIME 类型。"""
    ext = Path(path).suffix.lower().lstrip(".")
    mime_map = {
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png", "gif": "image/gif",
        "bmp": "image/bmp", "webp": "image/webp",
        "wav": "audio/wav", "mp3": "audio/mpeg",
        "ogg": "audio/ogg", "flac": "audio/flac",
        "opus": "audio/opus",
        "mp4": "video/mp4", "avi": "video/x-msvideo",
        "mov": "video/quicktime", "webm": "video/webm",
    }
    return mime_map.get(ext, "application/octet-stream")


def _has_media(input_content: Dict[str, Any]) -> bool:
    """判断输入中是否包含媒体数据。"""
    for key in ("image", "audio", "video"):
        items = input_content.get(key)
        if isinstance(items, list) and len(items) > 0:
            return True
    return False


def _resolve_media_item(item: Dict[str, str]) -> tuple[Optional[str], Optional[str]]:
    """解析单个媒体项，返回 (data_uri_or_url, source_type)。

    item 格式: {"type": "file|url|base64", "data": "..."}
    """
    item_type = item.get("type", "")
    data = item.get("data", "")
    if not data:
        return None, None

    if item_type == "url":
        return data, "url"
    elif item_type == "file":
        p = Path(data)
        if p.exists():
            mime = _get_mime_type(p)
            b64 = _base64_encode(p)
            return f"data:{mime};base64,{b64}", "file"
        else:
            logger.warning(f"Media file not found: {data}")
            return None, None
    elif item_type == "base64":
        if data.startswith("data:"):
            return data, "base64"
        mime = item.get("mime", "application/octet-stream")
        return f"data:{mime};base64,{data}", "base64"
    else:
        logger.warning(f"Unknown media item type: {item_type}")
        return None, None


# ── 构建多模态 content 数组 ──────────────────────────────────

def _build_image_content(input_content: Dict[str, Any]) -> Optional[list[dict]]:
    """构建图片的多模态 content 数组，支持多张图片。"""
    items = input_content.get("image")
    if not isinstance(items, list) or len(items) == 0:
        return None

    content_parts: list[dict] = []
    for item in items:
        uri, _ = _resolve_media_item(item)
        if uri:
            content_parts.append({"type": "image_url", "image_url": {"url": uri}})

    if not content_parts:
        return None

    user_text = input_content.get("text", "")
    prompt = _IMAGE_PROMPT
    if user_text:
        prompt += f'\n\nThe user also said: "{user_text}". Take this into account in your description.'

    return [{"type": "text", "text": prompt}] + content_parts


def _build_audio_content(input_content: Dict[str, Any]) -> Optional[list[dict]]:
    """构建音频的多模态 content 数组。

    注意：音频识别不能包含文本内容，否则会导致参数错误。
    """
    items = input_content.get("audio")
    if not isinstance(items, list) or len(items) == 0:
        return None

    content_parts: list[dict] = []
    for item in items:
        uri, _ = _resolve_media_item(item)
        if uri:
            content_parts.append({"type": "input_audio", "input_audio": {"data": uri}})

    if not content_parts:
        return None

    return content_parts


def _build_video_content(input_content: Dict[str, Any]) -> Optional[list[dict]]:
    """构建视频的多模态 content 数组。"""
    items = input_content.get("video")
    if not isinstance(items, list) or len(items) == 0:
        return None

    content_parts: list[dict] = []
    for item in items:
        uri, _ = _resolve_media_item(item)
        if uri:
            content_parts.append({"type": "video_url", "video_url": {"url": uri}})

    if not content_parts:
        return None

    user_text = input_content.get("text", "")
    prompt = _VIDEO_PROMPT
    if user_text:
        prompt += f'\n\nThe user also said: "{user_text}". Take this into account in your description.'

    return [{"type": "text", "text": prompt}] + content_parts


# ── 公开接口 ────────────────────────────────────────────────

async def process_media(input_content: Dict[str, Any]) -> str:
    """将包含媒体的输入通过多模态模型预处理为纯文本描述。

    处理流程：
    1. 检测 input_content 中是否包含 image/audio/video
    2. 如果没有媒体字段，直接返回原始 text
    3. 针对不同媒体类型，从 models.yaml 中读取专属模型分别处理
    4. 将所有文本描述合并返回

    Args:
        input_content: 消息 dict，可能包含 text/image/audio/video 等字段

    Returns:
        纯文本字符串，可直接交给 Agent 处理
    """
    if isinstance(input_content, str):
        return input_content

    text = input_content.get("text", "")

    if not _has_media(input_content):
        return text

    registry = ModelRegistry.get_instance()

    builders = [
        ("audio", _build_audio_content),
        ("image", _build_image_content),
        ("video", _build_video_content),
    ]

    _model_cache: dict[str, Any] = {}
    parts = []
    if text:
        parts.append(text)

    for media_type, builder in builders:
        content = builder(input_content)
        if content is None:
            continue

        model_name = registry.get_multimodal_model(media_type)
        if not model_name:
            logger.warning(f"No model configured for {media_type}, falling back to default model")

        cache_key = model_name or "__default__"
        if cache_key not in _model_cache:
            _model_cache[cache_key] = registry.create_chat_model(
                name=model_name,
                request_timeout=120,
            )
        llm = _model_cache[cache_key]

        try:
            logger.info(f"Processing {media_type} media with model: {model_name or 'default'}")
            response = await llm.ainvoke([HumanMessage(content=content)])
            extracted_text = response.content if hasattr(response, "content") else str(response)
            logger.info(f"Media processing complete, extracted {len(extracted_text)} chars from {media_type}")

            if extracted_text:
                parts.append(extracted_text)
        except Exception as e:
            logger.exception(f"Failed to process {media_type} media with model '{model_name}': {e}")
            parts.append(f"[System: Failed to process {media_type} content - {e}]")

    if not parts:
        logger.warning("Media fields present but failed to build content, returning original text")
        return text

    return "\n\n".join(parts)
