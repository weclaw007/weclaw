"""媒体处理器实现"""

from weclaw.media.processors.openai_processor import OpenAIProcessor
from weclaw.media.processors.dashscope_processor import DashScopeProcessor

__all__ = [
    "OpenAIProcessor",
    "DashScopeProcessor",
]
