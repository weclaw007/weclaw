"""
媒体处理器抽象基类与数据结构定义。

基类只定义 process() 抽象方法，不包含任何协议特定的实现逻辑。
各子类（OpenAI/DashScope 等）自行负责：
  - 输入数据的格式转换
  - API/SDK 的调用方式
  - 响应结果的解析
"""

import base64
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── 数据结构 ────────────────────────────────────────────────


@dataclass
class MediaItem:
    """单个媒体项

    Attributes:
        type: 数据类型 (file / url / base64)
        data: 数据内容（文件路径 / URL / base64 字符串）
        mime: MIME 类型（可选，用于 base64 图片/视频）
        format: 格式（可选，用于音频，如 wav / mp3）
    """
    type: str       # file, url, base64
    data: str
    mime: str = ""
    format: str = ""


@dataclass
class MediaInput:
    """统一的媒体输入数据结构

    Attributes:
        text: 用户附带的文本内容（可选）
        image: 图片列表
        audio: 音频列表
        video: 视频列表
    """
    text: str = ""
    image: List[MediaItem] = field(default_factory=list)
    audio: List[MediaItem] = field(default_factory=list)
    video: List[MediaItem] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MediaInput":
        """从前端传入的字典创建 MediaInput 实例

        Args:
            data: 前端格式的字典，或纯字符串

        Returns:
            MediaInput 实例
        """
        if isinstance(data, str):
            return cls(text=data)

        def _parse_items(items: Any) -> List[MediaItem]:
            if not items or not isinstance(items, list):
                return []
            result = []
            for item in items:
                if isinstance(item, dict):
                    result.append(MediaItem(
                        type=item.get("type", ""),
                        data=item.get("data", ""),
                        mime=item.get("mime", ""),
                        format=item.get("format", ""),
                    ))
            return result

        return cls(
            text=data.get("text", ""),
            image=_parse_items(data.get("image")),
            audio=_parse_items(data.get("audio")),
            video=_parse_items(data.get("video")),
        )

    def has_media(self) -> bool:
        """判断是否包含媒体数据"""
        return bool(self.image or self.audio or self.video)

    def get_media_types(self) -> List[str]:
        """获取包含的媒体类型列表（按 image → audio → video 顺序）"""
        types = []
        if self.image:
            types.append("image")
        if self.audio:
            types.append("audio")
        if self.video:
            types.append("video")
        return types


@dataclass
class MediaResult:
    """媒体处理结果

    Attributes:
        text: 提取 / 生成的文本内容
        media_type: 媒体类型标识（image / audio / video / image+audio …）
        success: 处理是否成功
        error: 错误信息（仅失败时）
        metadata: 额外元数据（厂商返回的 token 用量等）
    """
    text: str
    media_type: str = ""
    success: bool = True
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── 辅助函数（供子类使用）────────────────────────────────────


def base64_encode_file(path: str | Path) -> str:
    """读取本地文件并返回 base64 编码字符串"""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def guess_mime_type(path: str | Path) -> str:
    """根据文件扩展名推断 MIME 类型"""
    ext = Path(path).suffix.lower().lstrip(".")
    _mime_map = {
        # 图片
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png", "gif": "image/gif",
        "bmp": "image/bmp", "webp": "image/webp",
        # 音频
        "wav": "audio/wav", "mp3": "audio/mpeg",
        "ogg": "audio/ogg", "flac": "audio/flac",
        # 视频
        "mp4": "video/mp4", "avi": "video/x-msvideo",
        "mov": "video/quicktime", "webm": "video/webm",
    }
    return _mime_map.get(ext, "application/octet-stream")


def normalize_audio_format(mime_or_ext: str) -> str:
    """将 MIME 类型或扩展名统一为短格式名（wav / mp3 / …）"""
    if "/" in mime_or_ext:
        fmt = mime_or_ext.split("/")[-1]
        return "mp3" if fmt == "mpeg" else fmt
    return mime_or_ext


def format_result_text(
    original_text: str,
    extracted_text: str,
    media_type_str: str,
) -> str:
    """将原始文本与媒体提取文本组合为最终输出

    Args:
        original_text: 用户原始文本
        extracted_text: 模型提取的文本
        media_type_str: 媒体类型标识（用于生成标签）

    Returns:
        合并后的文本
    """
    _labels = {
        "audio": "[语音转文字]",
        "image": "[图片内容描述]",
        "video": "[视频内容描述]",
        "image+audio": "[图片与音频内容描述]",
        "audio+video": "[音频与视频内容描述]",
        "image+video": "[图片与视频内容描述]",
        "image+audio+video": "[多媒体内容描述]",
    }
    label = _labels.get(media_type_str, "[媒体内容]")

    parts = []
    if original_text:
        parts.append(original_text)
    if extracted_text:
        parts.append(f"{label}\n{extracted_text}")

    return "\n\n".join(parts) if parts else ""


# ── 抽象基类 ────────────────────────────────────────────────


class BaseMediaProcessor(ABC):
    """媒体处理器抽象基类

    子类只需实现 process() 方法。
    便捷方法（process_image / process_audio / process_video）
    默认通过构造 MediaInput 后委托给 process()，子类可按需覆盖。
    """

    def __init__(self, config: Dict[str, Any] | None = None):
        """
        Args:
            config: 处理器配置字典
        """
        self.config = config or {}

    # ── 核心抽象方法 ─────────────────────────────────────────

    @abstractmethod
    async def process(self, input_data: MediaInput) -> MediaResult:
        """处理媒体输入并返回结果

        Args:
            input_data: 统一的媒体输入

        Returns:
            MediaResult 处理结果
        """
        ...

    # ── 便捷方法 ─────────────────────────────────────────────

    async def process_image(
        self,
        image_data: str,
        image_type: str = "file",
        prompt: str = "",
        **kwargs,
    ) -> MediaResult:
        """处理单张图片"""
        return await self.process(MediaInput(
            text=prompt,
            image=[MediaItem(type=image_type, data=image_data)],
        ))

    async def process_audio(
        self,
        audio_data: str,
        audio_type: str = "file",
        audio_format: str = "wav",
        **kwargs,
    ) -> MediaResult:
        """处理单个音频"""
        return await self.process(MediaInput(
            audio=[MediaItem(type=audio_type, data=audio_data, format=audio_format)],
        ))

    async def process_video(
        self,
        video_data: str,
        video_type: str = "file",
        prompt: str = "",
        **kwargs,
    ) -> MediaResult:
        """处理单个视频"""
        return await self.process(MediaInput(
            text=prompt,
            video=[MediaItem(type=video_type, data=video_data)],
        ))
