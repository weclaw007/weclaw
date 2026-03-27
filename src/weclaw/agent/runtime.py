"""Agent 运行时 - 统一管理 Agent 生命周期、工具注册。

将 Session 和 BaseAdapter 中重复的 Agent 初始化逻辑抽取到此模块：
- 构建系统提示词
- 注册 message / timer_job 等业务工具
- 实例化 Agent 并初始化

所有入口（WebSocket Session、FeishuAdapter、TelegramAdapter）通过组合
AgentRuntime 来获取 Agent 实例，而不是各自重复初始化逻辑。
"""

import logging
from typing import Any, Protocol, runtime_checkable

from langchain_core.tools import BaseTool, tool

from weclaw.agent.graph import Agent
from weclaw.agent.prompts import build_system_prompt
from weclaw.utils.agent_config import AgentConfig
from weclaw.utils.paths import get_active_skills_dir

logger = logging.getLogger(__name__)


# ── MessageTransport 协议 ──────────────────────────────────────


@runtime_checkable
class MessageTransport(Protocol):
    """消息传输协议 - 定义 message 工具的底层通信接口。

    不同入口（WebSocket / 飞书 / Telegram）实现此协议，
    AgentRuntime 会自动注册一个统一的 `message` 工具并路由到对应实现。
    """

    async def send_message(self, query_params: dict) -> dict:
        """处理 message 工具调用。

        Args:
            query_params: 包含 action 字段的参数字典

        Returns:
            执行结果字典
        """
        ...


# ── AgentRuntime ───────────────────────────────────────────────


class AgentRuntime:
    """Agent 运行时：统一管理 Agent 初始化和生命周期。

    使用方式：
        runtime = AgentRuntime(
            session_id="feishu",
            message_transport=feishu_transport,  # 可选
        )
        await runtime.initialize(inject_prompt="...")
        agent = runtime.agent
    """

    def __init__(
        self,
        session_id: str = "main",
        config: AgentConfig | None = None,
        message_transport: MessageTransport | None = None,
        extra_tools: list[BaseTool] | None = None,
    ) -> None:
        self.session_id = session_id
        self.config = config or AgentConfig(session_id=session_id)
        self._message_transport = message_transport
        self._extra_tools = extra_tools or []
        self.agent: Agent | None = None

    async def initialize(
        self,
        inject_prompt: str = "",
        model_name: str | None = None,
    ) -> Agent:
        """初始化 Agent（幂等，重复调用直接返回已有实例）。

        Args:
            inject_prompt: 额外注入的 prompt（如 SKILL.md 内容）
            model_name: 模型配置名，为 None 时使用默认模型

        Returns:
            初始化后的 Agent 实例
        """
        if self.agent is not None and self.agent.agent is not None:
            return self.agent

        # 上次初始化失败的半成品需要清理
        if self.agent is not None:
            await self.agent.close()
            self.agent = None

        # 1. 构建系统提示词（不含技能部分，由 SkillsMiddleware 自动注入）
        system_prompt = build_system_prompt(agent_config=self.config)
        if inject_prompt:
            system_prompt += "\n\n" + inject_prompt

        # 2. 组装自定义工具
        custom_tools: list[BaseTool] = []

        # message 工具（如果提供了 transport）
        if self._message_transport is not None:
            custom_tools.append(self._create_message_tool())

        # 额外的业务工具（如 timer_job）
        custom_tools.extend(self._extra_tools)

        # 3. 构建 skills 路径（相对于 HOME，供 SkillsMiddleware 扫描）
        active_skills_dir = get_active_skills_dir()
        skills: list[str] | None = None
        if active_skills_dir.exists():
            # 使用相对于 HOME 的 POSIX 路径（LocalShellBackend root_dir=HOME）
            # active_skills_dir = ~/.weclaw/active_skills/ → 相对路径 = .weclaw/active_skills
            from pathlib import Path
            skills = [str(active_skills_dir.relative_to(Path.home()))]

        # 4. 初始化 Agent
        self.agent = Agent()
        await self.agent.init(
            system_prompt=system_prompt,
            model_name=model_name,
            custom_tools=custom_tools,
            session_id=self.session_id,
            skills=skills,
        )
        logger.info(f"[{self.session_id}] AgentRuntime 初始化成功")
        return self.agent

    def _create_message_tool(self) -> BaseTool:
        """创建统一的 message 工具，路由到 MessageTransport 实现。"""
        transport = self._message_transport

        @tool
        async def message(query_params: dict) -> dict:
            """处理所有的 channel 信息（如 feishu-channel、wechat-channel）。
            query_params 参数: json 对象，每个消息必须有 action 字段。
            支持的 action: send_pic, send_text, send_file, send_video
            """
            if "action" not in query_params:
                return {"error": "query_params must contain 'action' field"}
            return await transport.send_message(query_params)

        return message

    async def close(self) -> None:
        """关闭 Agent，释放资源。"""
        if self.agent:
            await self.agent.close()
            self.agent = None
            logger.info(f"[{self.session_id}] AgentRuntime 已关闭")

    def set_message_transport(self, transport: MessageTransport) -> None:
        """设置消息传输层（在 initialize 之前调用）。

        Args:
            transport: 实现 MessageTransport 协议的传输层实例

        Raises:
            RuntimeError: 如果 Agent 已初始化，不允许更换 transport
        """
        if self.agent is not None:
            raise RuntimeError("Agent 已初始化，不能更换 MessageTransport")
        self._message_transport = transport
