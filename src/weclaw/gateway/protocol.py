"""WebSocket 消息协议定义"""

from enum import StrEnum


class MsgType(StrEnum):
    USER = "user"
    SYSTEM = "system"
    TOOL = "tool"
    START = "start"
    CHUNK = "chunk"
    END = "end"
    ERROR = "error"
