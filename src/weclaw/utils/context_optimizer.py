"""上下文优化工具模块。

提供对话上下文精简、文本摘要等通用功能，
可被 Agent 及其他模块导入使用。
"""

import logging
import os

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph.message import RemoveMessage

logger = logging.getLogger(__name__)

# 默认模型与网关；仅在环境变量未设置时使用。
_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# 摘要使用的轻量模型名称
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

    llm = init_chat_model(
        model=SUMMARY_MODEL,
        model_provider="openai",
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url=os.getenv("BASE_URL") or _DEFAULT_BASE_URL,
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


def trim_old_rounds(messages: list, keep_recent: int = 4) -> list:
    """保留最近 keep_recent 轮对话，删除更早的轮次。

    返回 RemoveMessage 列表，可直接用于 LangGraph state 中安全地删除消息。
    按完整轮次删除保证 AIMessage ↔ ToolMessage 配对不被破坏。

    Args:
        messages: 完整的消息列表。
        keep_recent: 保留最近的轮次数（一轮 = HumanMessage + 后续所有回复）。

    Returns:
        需要删除的 RemoveMessage 列表；若无需裁剪则返回空列表。
    """
    rounds = split_into_rounds(messages)

    # 区分 SystemMessage 轮次和对话轮次
    dialog_rounds: list[list] = []
    for r in rounds:
        if not (len(r) == 1 and isinstance(r[0], SystemMessage)):
            dialog_rounds.append(r)

    # 对话轮次不足 keep_recent，无需裁剪
    if len(dialog_rounds) <= keep_recent:
        return []

    rounds_to_remove = dialog_rounds[:-keep_recent]

    # 整轮生成 RemoveMessage，不会破坏消息配对
    removals = []
    for round_msgs in rounds_to_remove:
        for msg in round_msgs:
            removals.append(RemoveMessage(id=msg.id))

    return removals
