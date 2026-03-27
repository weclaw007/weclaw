"""消息构建工具函数 - 提供统一的消息格式构建方法"""


def build_user_message(message_id: str, text: str, **kwargs) -> dict:
    """构建用户消息格式"""
    message = {"id": message_id, "type": "user", "text": text}
    message.update(kwargs)
    return message


def build_system_message(**kwargs) -> dict:
    """构建系统消息格式"""
    message = {"type": "system"}
    message.update(kwargs)
    return message


def build_tool_message(message_id: str, **kwargs) -> dict:
    """构建工具消息格式"""
    message = {"id": message_id, "type": "tool"}
    message.update(kwargs)
    return message


# ── 流式响应消息 ──

def build_stream_start() -> dict:
    """构建流式响应开始消息"""
    return {"type": "start"}


def build_stream_chunk(chunk: str) -> dict:
    """构建流式响应片段消息"""
    return {"type": "chunk", "chunk": chunk}


def build_stream_end() -> dict:
    """构建流式响应结束消息"""
    return {"type": "end"}


def build_error_message(error: str) -> dict:
    """构建错误消息"""
    return {"type": "error", "error": error}
