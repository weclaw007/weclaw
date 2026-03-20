"""上下文优化工具模块。

提供对话上下文精简、文本摘要、工具结果归档等通用功能，
可被 Agent 及其他模块导入使用。
"""

import logging

from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage

from weclaw.utils.model_registry import ModelRegistry
from weclaw.utils.paths import get_tool_archive_dir

logger = logging.getLogger(__name__)

# 摘要请求超时时间（秒）
SUMMARY_TIMEOUT = 30

# 摘要标记前缀，用于识别摘要 SystemMessage
SUMMARY_MARKER = "[Summary of previous conversation]"


async def summarize_text(content: str, prompt: str | None = None, max_length: int = 200) -> str:
    """使用轻量模型对一段文本生成摘要。

    创建临时的轻量模型实例，调用完成后自动释放。
    可被任意模块调用，不依赖 Agent 类。

    摘要模型名从 models.yaml 的 summary_model 字段读取，
    未配置时回退到 default 模型。

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
    summary_model_name = registry.get_summary_model()
    llm = registry.create_chat_model(
        name=summary_model_name,
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


def serialize_messages_to_text(messages: list) -> str:
    """将消息列表序列化为纯文本，供摘要模型阅读。

    将 HumanMessage / AIMessage / ToolMessage 等统一转为可读文本，
    避免将原始 Message 对象直接传给摘要模型导致 API 报错。
    """
    lines: list[str] = []
    for msg in messages:
        role = msg.type  # "human" / "ai" / "tool" / "system"
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        # AI 消息可能附带 tool_calls，也一并序列化
        if role == "ai" and hasattr(msg, "tool_calls") and msg.tool_calls:
            tool_calls_text = ", ".join(
                f"{tc.get('name', 'unknown')}({str(tc.get('args', {}))[:120]})"
                for tc in msg.tool_calls
            )
            if content:
                lines.append(f"[Assistant]: {content}\n  (called tools: {tool_calls_text})")
            else:
                lines.append(f"[Assistant]: (called tools: {tool_calls_text})")
        elif role == "human":
            lines.append(f"[User]: {content}")
        elif role == "tool":
            tool_name = getattr(msg, "name", "") or "tool"
            # 截断过长的工具结果
            display = content[:500] + "..." if len(content) > 500 else content
            lines.append(f"[Tool Result ({tool_name})]: {display}")
        elif role == "system":
            lines.append(f"[System]: {content}")
        else:
            lines.append(f"[{role}]: {content}")
    return "\n".join(lines)


async def summarize_and_rebuild_messages(
    messages: list,
    summary_llm,
    max_token_limit: int = 10000,
    keep_recent_rounds: int = 6,
) -> tuple[list, list, "SystemMessage | None"] | None:
    """检查消息列表 token 数，超过阈值时生成摘要并返回重建所需的操作。

    压缩策略：
    - 保留所有 SystemMessage（系统提示词）
    - 按完整轮次（split_into_rounds）切分，保留最近 keep_recent_rounds 轮
    - 对更早的旧轮次序列化为纯文本后调用小模型生成摘要
    - 返回需要删除的 RemoveMessage 列表、新摘要消息和需要重新添加的近期消息

    Args:
        messages: 当前完整消息列表（从 state 中获取）
        summary_llm: 用于生成摘要的 LLM 实例
        max_token_limit: 触发压缩的 token 阈值
        keep_recent_rounds: 保留最近几轮完整对话不压缩

    Returns:
        如果不需要压缩返回 None；
        否则返回 (all_removals, recent_messages_flat, summary_msg) 三元组：
        - all_removals: 需要删除的 RemoveMessage 列表
        - recent_messages_flat: 需要重新添加的近期消息列表
        - summary_msg: 新的摘要 SystemMessage
    """
    if not messages:
        return None

    # 估算 token 数（使用字符数粗估，避免额外 API 调用）
    total_chars = sum(
        len(m.content) if isinstance(m.content, str) else len(str(m.content))
        for m in messages
    )
    # 粗估：中文约 1.5 字符/token，英文约 4 字符/token，取保守值 2 字符/token
    estimated_tokens = total_chars // 2

    # 这个总长度只是所有Message 内容长度，不包括 组装成json 格式需要的额外数据，还不包括系统提示词
    if estimated_tokens <= max_token_limit:
        return None

    logger.info(
        f"Estimated tokens {estimated_tokens} exceeds limit {max_token_limit}, "
        f"starting context summarization..."
    )

    # --- Step 1: 分离 SystemMessage 与对话消息 ---
    system_prompt_messages: list = []   # 纯系统提示词
    old_summary_messages: list = []     # 旧的摘要 SystemMessage（需删除）
    non_system_messages: list = []      # 非 SystemMessage 的对话消息

    for msg in messages:
        if isinstance(msg, SystemMessage):
            content_str = msg.content if isinstance(msg.content, str) else str(msg.content)
            if SUMMARY_MARKER in content_str:
                old_summary_messages.append(msg)
            else:
                system_prompt_messages.append(msg)
        else:
            non_system_messages.append(msg)

    # --- Step 2: 对非 system 消息按完整轮次切分 ---
    dialog_rounds = split_into_rounds(non_system_messages)

    if len(dialog_rounds) <= keep_recent_rounds:
        logger.info("Dialog rounds not enough for summarization, skipping")
        return None

    # --- Step 3: 切分旧轮次和近期轮次 ---
    old_rounds = dialog_rounds[:-keep_recent_rounds]
    recent_rounds = dialog_rounds[-keep_recent_rounds:]

    # 将旧轮次的消息展平并序列化为纯文本
    old_messages_flat: list = []
    for r in old_rounds:
        old_messages_flat.extend(r)

    # 把旧摘要的文本也纳入新的摘要输入，确保历史信息不丢失
    old_summary_text = ""
    if old_summary_messages:
        old_summary_text = "\n".join(
            m.content if isinstance(m.content, str) else str(m.content)
            for m in old_summary_messages
        ) + "\n\n"

    conversation_text = old_summary_text + serialize_messages_to_text(old_messages_flat)

    # --- Step 4: 调用小模型生成摘要 ---
    summary_response = await summary_llm.ainvoke([
        SystemMessage(
            content="Please summarize the following conversation history concisely, "
                    "retaining all key information, conclusions, and important details."
        ),
        HumanMessage(content=conversation_text),
    ])
    summary_text = summary_response.content if hasattr(summary_response, "content") else str(summary_response)

    # --- Step 5: 构建 RemoveMessage 列表和新摘要消息 ---
    remove_old = [RemoveMessage(id=m.id) for m in old_messages_flat]
    remove_old_summary = [RemoveMessage(id=m.id) for m in old_summary_messages]

    recent_messages_flat: list = []
    for r in recent_rounds:
        recent_messages_flat.extend(r)
    remove_recent = [RemoveMessage(id=m.id) for m in recent_messages_flat]

    all_removals = remove_old + remove_old_summary + remove_recent
    summary_msg = SystemMessage(content=f"{SUMMARY_MARKER}\n{summary_text}")

    logger.info(
        f"Context summarization done: {len(old_rounds)} old rounds ({len(old_messages_flat)} messages) "
        f"+ {len(old_summary_messages)} old summary(s) "
        f"→ will remove & replace with 1 summary, keep recent {len(recent_rounds)} rounds"
    )

    return (all_removals, recent_messages_flat, summary_msg)
