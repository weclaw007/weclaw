"""人格设置相关的系统消息处理器"""
import logging

from weclaw.agent.handlers.base import BaseHandler, ClientContext

logger = logging.getLogger(__name__)


class PersonaHandler(BaseHandler):
    """处理人格设置相关的系统消息：获取和更新 agent 人格"""

    ACTIONS = {"get_persona", "set_persona"}

    def __init__(self, websocket, ctx: ClientContext):
        super().__init__(websocket)
        self._ctx = ctx

    async def handle_get_persona(self, message: dict) -> None:
        """获取当前人格设置"""
        message_id = message.get("id", "")
        persona = self._ctx.config.persona
        await self.send_response(
            message_id, "get_persona", persona=persona
        )

    async def handle_set_persona(self, message: dict) -> None:
        """设置人格并重置 Agent 以使新人格生效"""
        message_id = message.get("id", "")
        persona = message.get("persona", "")

        try:
            self._ctx.config.persona = persona
            # 重置 Agent，下次对话时会用新人格重新初始化
            await self._ctx.reset_agent()
            logger.info(f"人格已更新: {persona[:50]}{'...' if len(persona) > 50 else ''}")
            await self.send_response(
                message_id, "set_persona", success=True
            )
        except Exception as e:
            logger.exception("设置人格失败")
            await self.send_response(
                message_id, "set_persona", success=False, error=str(e)
            )
