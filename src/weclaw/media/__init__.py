"""
多媒体处理模块：将音频、图片、视频等多媒体输入通过多模态模型转换为纯文本。

架构设计：
  BaseMediaProcessor（抽象基类）
      ├── OpenAIProcessor      - OpenAI 兼容协议
      ├── DashScopeProcessor   - 阿里云 DashScope SDK
      └── ...                  - 可扩展

  MediaProcessorFactory 根据配置创建对应的处理器实例。

参数格式（统一列表）：
{
    "text": "描述这些内容",
    "image": [
        {"type": "file", "data": "/path/to/image.jpg"},
        {"type": "url", "data": "https://example.com/image.jpg"},
        {"type": "base64", "data": "base64_string", "mime": "image/jpeg"}
    ],
    "audio": [
        {"type": "file", "data": "/path/to/audio.wav"},
        {"type": "base64", "data": "base64_string", "format": "wav"}
    ],
    "video": [
        {"type": "file", "data": "/path/to/video.mp4"},
        {"type": "url", "data": "https://example.com/video.mp4"}
    ]
}
"""

from weclaw.media.base import BaseMediaProcessor, MediaInput, MediaItem, MediaResult
from weclaw.media.factory import MediaProcessorFactory

__all__ = [
    "BaseMediaProcessor",
    "MediaInput",
    "MediaItem",
    "MediaResult",
    "MediaProcessorFactory",
]
