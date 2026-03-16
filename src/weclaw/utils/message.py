"""
消息构建工具函数

提供统一的消息格式构建方法，供各个技能（skill）模块复用。
"""


def build_user_message(message_id: str, text: str, **kwargs) -> dict:
    """构建用户消息格式，给大模型分析

    Args:
        message_id: 消息唯一 ID
        text: 消息文本内容
        **kwargs: 其他业务相关字段，如 location、image 等

    Returns:
        dict: 包含通用字段和业务字段的消息对象
    """
    message = {
        "id": message_id,
        "type": "user",
        "text": text
    }
    # 合并其他业务字段
    message.update(kwargs)
    return message


def build_system_message(**kwargs) -> dict:
    """构建系统消息格式

    Args:
        **kwargs: 可变参数，用于传递系统消息相关的数据

    Returns:
        dict: 系统消息字典
    """
    message = {
        "type": "system"
    }
    # 将可变参数添加到消息中
    message.update(kwargs)
    return message


def build_tool_message(message_id: str, **kwargs) -> dict:
    """构建工具消息格式

    Args:
        message_id: 消息 ID
        **kwargs: 可变参数，用于传递工具调用相关的数据

    Returns:
        dict: 工具消息字典
    """
    message = {
        "id": message_id,
        "type": "tool"
    }
    # 将可变参数添加到消息中
    message.update(kwargs)
    return message
