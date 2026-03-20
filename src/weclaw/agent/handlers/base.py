"""系统消息处理器基类"""
import json
import logging
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from weclaw.utils.agent_config import AgentConfig

logger = logging.getLogger(__name__)


@runtime_checkable
class ClientContext(Protocol):
    """Handler 可访问的 Client 上下文接口。

    Handler 仅通过此 Protocol 与 Client 交互，避免直接依赖具体的 Client 类，
    从而实现解耦。单元测试时可传入 Mock 对象。
    """

    session_id: str
    """当前会话 ID，每个 agent 独立配置"""

    model_name: str | None
    """当前使用的模型配置名"""

    inject_prompt: str
    """注入的系统提示词"""

    config: "AgentConfig"
    """Agent 配置管理器，每个 session 独立"""

    async def reset_agent(self) -> None:
        """重置 Agent：销毁旧实例，下次对话时会用新配置重新初始化"""
        ...


class BaseHandler:
    """所有系统消息 Handler 的基类。

    子类需要：
    1. 定义 ACTIONS: set[str]，声明自己能处理的 action 列表
    2. 实现对应的 handle_<action>(message) 异步方法
    """

    ACTIONS: set[str] = set()

    def __init__(self, websocket):
        self.websocket = websocket

    def can_handle(self, action: str) -> bool:
        """判断当前 Handler 是否能处理指定的 action"""
        return action in self.ACTIONS

    async def handle(self, action: str, message: dict) -> None:
        """根据 action 分发到具体处理方法"""
        method = getattr(self, f"handle_{action}", None)
        if method:
            await method(message)
        else:
            logger.warning(f"Handler {type(self).__name__} 未实现 action: {action}")

    async def send_response(self, message_id: str, action: str, **kwargs) -> None:
        """统一的响应发送方法，减少重复的 json.dumps 代码"""
        response = {
            "id": message_id,
            "type": "system",
            "action": action,
            **kwargs,
        }
        await self.websocket.send(json.dumps(response, ensure_ascii=False))
