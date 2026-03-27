"""人格设置相关的系统消息处理器"""

import logging

from weclaw.agent.handlers.base import BaseHandler, ClientContext

logger = logging.getLogger(__name__)


class PersonaHandler(BaseHandler):
    ACTIONS = {"get_persona", "set_persona"}

    def __init__(self, websocket, ctx: ClientContext):
        super().__init__(websocket)
        self._ctx = ctx

    async def handle_get_persona(self, message: dict) -> None:
        message_id = message.get("id", "")
        await self.send_response(message_id, "get_persona", persona=self._ctx.config.persona)

    async def handle_set_persona(self, message: dict) -> None:
        message_id = message.get("id", "")
        persona = message.get("persona", "")
        try:
            self._ctx.config.persona = persona
            await self._ctx.reset_agent()
            await self.send_response(message_id, "set_persona", success=True)
        except Exception as e:
            await self.send_response(message_id, "set_persona", success=False, error=str(e))
