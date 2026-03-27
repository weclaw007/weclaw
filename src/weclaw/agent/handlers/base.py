"""系统消息处理器基类"""

import json
import logging
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from weclaw.utils.agent_config import AgentConfig

logger = logging.getLogger(__name__)


@runtime_checkable
class ClientContext(Protocol):
    """Handler 可访问的 Client 上下文接口。"""

    session_id: str
    model_name: str | None
    inject_prompt: str
    config: "AgentConfig"

    async def reset_agent(self) -> None: ...


class BaseHandler:
    """所有系统消息 Handler 的基类。"""

    ACTIONS: set[str] = set()

    def __init__(self, websocket):
        self.websocket = websocket

    def can_handle(self, action: str) -> bool:
        return action in self.ACTIONS

    async def handle(self, action: str, message: dict) -> None:
        method = getattr(self, f"handle_{action}", None)
        if method:
            await method(message)
        else:
            logger.warning(f"Handler {type(self).__name__} 未实现 action: {action}")

    async def send_response(self, message_id: str, action: str, **kwargs) -> None:
        response = {"id": message_id, "type": "system", "action": action, **kwargs}
        await self.websocket.send(json.dumps(response, ensure_ascii=False))
