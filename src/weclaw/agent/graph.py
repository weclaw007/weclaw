"""Agent 核心 - 基于 DeepAgents create_deep_agent 的智能体实现。

相比 v1 的变化：
- create_agent → create_deep_agent（自动获得 9 个内置工具 + 4 大 Middleware）
- 删除 context_optimizer（上下文管理交给 DeepAgents 内置 VFS + StateBackend）
- 删除 read_tool_result（VFS 自动处理长内容卸载）
- 删除 summary_llm（不再需要摘要小模型）
- 技能执行由 SkillsMiddleware 自动注入技能列表，主 Agent 通过 read_file + execute 直接执行
"""

import logging
from pathlib import Path
from typing import Any, AsyncIterator

import aiosqlite
from deepagents import create_deep_agent
from deepagents.backends.local_shell import LocalShellBackend
from langchain_core.messages import AIMessageChunk
from langchain_core.tools import BaseTool
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from weclaw.agent.subagents import get_subagents_config
from weclaw.utils.model_registry import ModelRegistry
from weclaw.utils.paths import get_checkpoint_db_path

logger = logging.getLogger(__name__)


class Agent:
    """封装 DeepAgents 模型初始化、工具注册与流式推理。

    DeepAgents 内置提供（通过 LocalShellBackend）：
    - FilesystemMiddleware: ls, read_file, write_file, edit_file, glob, grep
    - execute: shell 命令执行（由 LocalShellBackend 提供）
    - TodoListMiddleware: write_todos
    - SubAgentMiddleware: task
    """

    def __init__(self, stream_mode: str = "messages") -> None:
        self.stream_mode = stream_mode
        self.agent: Any | None = None
        self.config: dict[str, Any] | None = None
        self._db_conn: aiosqlite.Connection | None = None
        self._session_id: str = "main"

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def init(
        self,
        system_prompt: str,
        model_name: str | None = None,
        custom_tools: list[BaseTool] | None = None,
        request_timeout: int = 120,
        session_id: str | None = None,
        skills: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """初始化 DeepAgents Agent。

        Args:
            system_prompt: 系统提示词
            model_name: 模型配置名（对应 models.yaml），为 None 时使用默认模型
            custom_tools: 自定义工具列表（如 message、timer_job 等业务工具）
            request_timeout: 请求超时时间（秒）
            session_id: 会话 ID，用于持久化检查点
            skills: 技能源目录路径列表（相对于 backend root_dir），
                    传入后 SkillsMiddleware 自动扫描并注入技能列表到 system prompt
        """
        # 关闭旧连接
        if self._db_conn is not None:
            await self._db_conn.close()
            self._db_conn = None

        # 创建 LLM
        registry = ModelRegistry.get_instance()
        llm = registry.create_chat_model(
            name=model_name,
            request_timeout=request_timeout,
            stream_usage=True,
        )

        # 会话持久化
        resolved_session_id = session_id or "main"
        self._session_id = resolved_session_id
        db_path = get_checkpoint_db_path(resolved_session_id)
        self._db_conn = await aiosqlite.connect(db_path)
        checkpoint = AsyncSqliteSaver(self._db_conn)
        await checkpoint.setup()
        self.config = {"configurable": {"thread_id": resolved_session_id}}

        # 组装工具：仅业务工具（技能执行由 SkillsMiddleware 自动处理）
        tools = list(custom_tools or [])

        # 使用 LocalShellBackend 让工具可以访问真实文件系统 + 执行 shell 命令
        # FilesystemBackend 只提供文件操作，不支持 execute
        # LocalShellBackend 继承 FilesystemBackend，额外提供 execute 工具
        backend = LocalShellBackend(root_dir=str(Path.home()), virtual_mode=False, inherit_env=True)

        # 创建 DeepAgents Agent（自动注入 9 个内置工具 + 4 大 Middleware）
        # skills 参数触发 SkillsMiddleware，自动扫描技能目录并注入技能列表到 system prompt
        self.agent = create_deep_agent(
            model=llm,
            tools=tools,
            checkpointer=checkpoint,
            system_prompt=system_prompt,
            subagents=get_subagents_config(),
            backend=backend,
            skills=skills,
        )

    async def close(self) -> None:
        """关闭 SQLite 连接，释放资源。"""
        if self._db_conn is not None:
            await self._db_conn.close()
            self._db_conn = None
            logger.info("SQLite checkpoint 连接已关闭")

    def _build_content(self, input_content: str | dict[str, Any]) -> list[dict[str, Any]]:
        """将输入转换为模型所需 content 结构。

        注意：当前流程中 media_processor 已在上游将媒体内容转为纯文本，
        因此 input_content 实际上始终为 str。保留 dict 分支仅作为防御性处理。
        """
        if isinstance(input_content, str):
            return [{"type": "text", "text": input_content}]
        text = input_content.get("text", "")
        return [{"type": "text", "text": text}] if text else []

    async def astream_text(
        self,
        content: str | dict[str, Any],
        context: Any = None,
    ) -> AsyncIterator[str]:
        """只输出文本分片，适用于流式响应。

        注意：v2 不再需要手动调用 _archive_tool_results 和 _summarize_if_needed，
        DeepAgents 的 FilesystemMiddleware 自动管理上下文。
        """
        llm_calls: list[dict[str, int]] = []
        total_input = 0
        total_output = 0

        async for message in self.astream(content, context):
            if isinstance(message, tuple) and len(message) > 0:
                chunk = message[0]
                if isinstance(chunk, AIMessageChunk):
                    usage = getattr(chunk, "usage_metadata", None)
                    if usage:
                        cur_in = usage.get("input_tokens", 0)
                        cur_out = usage.get("output_tokens", 0)
                        if cur_in or cur_out:
                            llm_calls.append({"input_tokens": cur_in, "output_tokens": cur_out})
                            total_input += cur_in
                            total_output += cur_out
                    raw_content = getattr(chunk, "content", "")
                    # content 可能是 str 或 list[dict]（工具调用时）
                    if isinstance(raw_content, str):
                        if raw_content:
                            yield raw_content
                    elif isinstance(raw_content, list):
                        for block in raw_content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                t = block.get("text", "")
                                if t:
                                    yield t

        if llm_calls:
            if len(llm_calls) > 1:
                for i, call in enumerate(llm_calls, 1):
                    logger.info(
                        f"  第 {i} 次 LLM 调用 - 输入: {call['input_tokens']}, "
                        f"输出: {call['output_tokens']}"
                    )
            logger.info(
                f"Token 用量 - 输入: {total_input}, 输出: {total_output}, "
                f"合计: {total_input + total_output} ({len(llm_calls)} 次 LLM 调用)"
            )

    async def astream(
        self,
        input_content: str | dict[str, Any],
        context: Any = None,
    ) -> AsyncIterator[Any]:
        """输出底层原始流事件。"""
        if self.agent is None or self.config is None:
            raise RuntimeError("Agent 尚未初始化，请先调用 await init(...)")

        content = self._build_content(input_content)

        try:
            async for chunk in self.agent.astream(
                {"messages": [{"role": "user", "content": content}]},
                stream_mode=self.stream_mode,
                config=self.config,
                context=context,
            ):
                yield chunk
        except Exception as e:
            logger.exception(f"Agent streaming error: {e}")
            return

