"""上下文优化工具模块。

提供对话上下文精简、文本摘要、工具结果归档等通用功能，
可被 Agent 及其他模块导入使用。
"""

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from weclaw.utils.model_registry import ModelRegistry
from weclaw.utils.paths import get_tool_archive_dir

logger = logging.getLogger(__name__)

# 摘要使用的轻量模型名称（对应 models.yaml 中的配置名）
SUMMARY_MODEL = "qwen-turbo"
# 摘要请求超时时间（秒）
SUMMARY_TIMEOUT = 30


async def summarize_text(content: str, prompt: str | None = None, max_length: int = 200) -> str:
    """使用轻量模型对一段文本生成摘要。

    创建临时的轻量模型实例，调用完成后自动释放。
    可被任意模块调用，不依赖 Agent 类。

    Args:
        content: 需要摘要的原始文本。
        prompt: 自定义的摘要提示词。为 None 时使用默认提示词。
        max_length: 摘要最大字数限制，用于默认提示词中。

    Returns:
        摘要文本。如果摘要失败则抛出异常。
    """
    if not content or not content.strip():
        return content

    registry = ModelRegistry.get_instance()
    llm = registry.create_chat_model(
        name=SUMMARY_MODEL,
        request_timeout=SUMMARY_TIMEOUT,
    )

    if prompt is None:
        prompt = (
            f"Please summarize the key points of the following content concisely "
            f"in the same language as the content, no more than {max_length} characters:\n\n{content}"
        )
    else:
        prompt = f"{prompt}\n\n{content}"

    response = await llm.ainvoke(prompt)
    summary = response.content if isinstance(response.content, str) else str(response.content)
    return summary.strip()


def split_into_rounds(messages: list) -> list[list]:
    """将消息列表按完整轮次切分。

    每一轮以 HumanMessage 开头，到下一个 HumanMessage 之前结束。
    SystemMessage 单独作为独立组保留。

    Args:
        messages: 完整的消息列表。

    Returns:
        切分后的轮次列表，每个元素为一轮中包含的消息列表。
    """
    rounds: list[list] = []
    current_round: list = []

    for msg in messages:
        if isinstance(msg, SystemMessage):
            # SystemMessage 始终保留，单独一组
            if current_round:
                rounds.append(current_round)
                current_round = []
            rounds.append([msg])
        elif isinstance(msg, HumanMessage):
            # 遇到新的 HumanMessage，前一轮结束
            if current_round:
                rounds.append(current_round)
            current_round = [msg]
        else:
            # AIMessage / ToolMessage 追加到当前轮
            current_round.append(msg)

    if current_round:
        rounds.append(current_round)

    return rounds


# 工具结果归档的内容长度阈值

# 工具结果归档的内容长度阈值（超过此长度的 ToolMessage 会被归档）
TOOL_ARCHIVE_MIN_LENGTH = 500

# 归档后替换标记前缀，用于识别已归档的消息
TOOL_ARCHIVE_PREFIX = "[Tool Result Archived]"


def archive_tool_result(session_id: str, tool_call_id: str, tool_name: str,
                        tool_args: str, content: str) -> str:
    """将工具调用结果归档到本地文件，返回替换后的摘要文本。

    Args:
        session_id: 会话 ID
        tool_call_id: 工具调用 ID（唯一标识）
        tool_name: 工具名称
        tool_args: 工具调用参数摘要
        content: 工具调用的完整结果内容

    Returns:
        归档后的替换文本
    """
    archive_dir = get_tool_archive_dir(session_id)
    # 使用 tool_call_id 作为文件名（去掉可能的特殊字符）
    safe_id = tool_call_id.replace("/", "_").replace("\\", "_")
    filepath = archive_dir / f"{safe_id}.txt"
    filepath.write_text(content, encoding="utf-8")
    logger.info(f"Archived tool result: {tool_name}({tool_args}) -> {filepath}")

    # 构造替换文本：保留足够线索让 LLM 判断是否需要读取原文
    replacement = (
        f"{TOOL_ARCHIVE_PREFIX} ID: {tool_call_id}\n"
        f"Tool: {tool_name}\n"
        f"Args: {tool_args}\n"
        f"Original content length: {len(content)} chars\n"
        f"To view full result, call read_tool_result with ID: {tool_call_id}"
    )
    return replacement


def read_archived_tool_result(session_id: str, tool_call_id: str) -> str:
    """从本地文件读取已归档的工具调用结果。

    Args:
        session_id: 会话 ID
        tool_call_id: 工具调用 ID

    Returns:
        原始工具调用结果内容，若文件不存在则返回错误提示
    """
    archive_dir = get_tool_archive_dir(session_id)
    safe_id = tool_call_id.replace("/", "_").replace("\\", "_")
    filepath = archive_dir / f"{safe_id}.txt"
    if filepath.exists():
        return filepath.read_text(encoding="utf-8")
    return f"Archived result not found for ID: {tool_call_id}"


def is_archived_tool_message(content: str) -> bool:
    """判断 ToolMessage 是否已经被归档替换过。"""
    return isinstance(content, str) and content.startswith(TOOL_ARCHIVE_PREFIX)
