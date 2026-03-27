"""适配器基类 - 定义 IM Bot 适配器的统一接口。

v3 重构：
- Agent 初始化逻辑移至 AgentRuntime（agent/runtime.py）
- BaseAdapter 不再直接管理 Agent 实例，而是通过 AgentRuntime 组合
- 子类不再需要重写 _get_custom_tools()，而是提供 MessageTransport
"""

import logging
from abc import ABC, abstractmethod

from weclaw.agent.media_processor import process_media
from weclaw.agent.runtime import AgentRuntime, MessageTransport
from weclaw.utils.agent_config import AgentConfig

logger = logging.getLogger(__name__)


class BaseAdapter(ABC):
    """IM Bot 适配器基类。

    每个适配器实例持有一个 AgentRuntime，生命周期与适配器相同。
    """

    _STOPPED_REPLY: str = "机器人已停止，发送 /start 重新启动。"

    def __init__(
        self,
        adapter_name: str,
        message_transport: MessageTransport | None = None,
    ) -> None:
        self.adapter_name = adapter_name
        self.config: AgentConfig = AgentConfig(session_id=adapter_name)
        self._runtime = AgentRuntime(
            session_id=adapter_name,
            config=self.config,
            message_transport=message_transport,
        )
        self._stopped = False

    @property
    def agent(self):
        """向后兼容：访问底层 Agent 实例。"""
        return self._runtime.agent

    async def initialize_agent(self, inject_prompt: str = "") -> None:
        """初始化 Agent（惰性调用，首次处理消息前自动触发）。"""
        await self._runtime.initialize(inject_prompt=inject_prompt)

    async def ask_agent(self, prompt: str) -> str:
        """向 Agent 发送消息并收集完整回复（非流式）。"""
        if self._runtime.agent is None:
            await self.initialize_agent()
        parts: list[str] = []
        async for chunk in self._runtime.agent.astream_text(prompt):
            parts.append(chunk)
        return "".join(parts)

    async def ask_agent_with_media(self, content: dict) -> str:
        """向 Agent 发送含媒体的消息并收集完整回复。"""
        if self._runtime.agent is None:
            await self.initialize_agent()
        prompt = await process_media(content)
        return await self.ask_agent(prompt)

    @abstractmethod
    async def start(self) -> None:
        """启动适配器（长运行，阻塞直到停止）。"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """停止适配器，释放资源。"""
        ...

    async def close(self) -> None:
        """关闭 Agent 和适配器资源。"""
        await self._runtime.close()
        logger.info(f"[{self.adapter_name}] 已关闭")
