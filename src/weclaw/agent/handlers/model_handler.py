"""模型相关的系统消息处理器"""

import logging

from weclaw.agent.handlers.base import BaseHandler, ClientContext

logger = logging.getLogger(__name__)


class ModelHandler(BaseHandler):
    ACTIONS = {"switch_model", "get_models"}

    def __init__(self, websocket, ctx: ClientContext):
        super().__init__(websocket)
        self._ctx = ctx

    async def handle_switch_model(self, message: dict) -> None:
        model_name = message.get("model_name", "")
        message_id = message.get("id", "")
        try:
            self._ctx.model_name = model_name if model_name else None
            await self._ctx.reset_agent()
            await self.send_response(message_id, "switch_model", model_name=model_name, success=True)
        except Exception as e:
            await self.send_response(message_id, "switch_model", success=False, error=str(e))

    async def handle_get_models(self, message: dict) -> None:
        from weclaw.utils.model_registry import ModelRegistry
        message_id = message.get("id", "")
        try:
            registry = ModelRegistry.get_instance()
            await self.send_response(
                message_id, "get_models",
                models=registry.list_available(),
                default=registry.get_default(),
                current=self._ctx.model_name or registry.get_default(),
            )
        except Exception as e:
            await self.send_response(message_id, "get_models", models=[], error=str(e))
