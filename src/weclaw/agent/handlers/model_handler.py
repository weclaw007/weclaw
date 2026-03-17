"""模型相关的系统消息处理器"""
import logging

from weclaw.agent.handlers.base import BaseHandler, ClientContext

logger = logging.getLogger(__name__)


class ModelHandler(BaseHandler):
    """处理模型管理相关的系统消息：切换模型、获取模型列表"""

    ACTIONS = {"switch_model", "get_models"}

    def __init__(self, websocket, ctx: ClientContext):
        super().__init__(websocket)
        self._ctx = ctx

    async def handle_switch_model(self, message: dict) -> None:
        """处理切换模型消息：销毁旧 Agent，下次对话时用新模型重新初始化"""
        model_name = message.get("model_name", "")
        message_id = message.get("id", "")

        try:
            self._ctx.model_name = model_name if model_name else None
            # 通过 Protocol 接口重置 Agent
            await self._ctx.reset_agent()

            logger.info(f"模型已切换为: {model_name or '默认'}")
            await self.send_response(
                message_id, "switch_model", model_name=model_name, success=True
            )
        except Exception as e:
            logger.exception(f"切换模型失败: {e}")
            await self.send_response(
                message_id, "switch_model", success=False, error=str(e)
            )

    async def handle_get_models(self, message: dict) -> None:
        """处理获取可用模型列表消息"""
        from weclaw.utils.model_registry import ModelRegistry

        message_id = message.get("id", "")
        try:
            registry = ModelRegistry.get_instance()
            models = registry.list_available()
            default_model = registry.get_default()
            current_model = self._ctx.model_name or default_model

            await self.send_response(
                message_id, "get_models",
                models=models,
                default=default_model,
                current=current_model,
            )
        except Exception as e:
            logger.exception(f"获取模型列表失败: {e}")
            await self.send_response(
                message_id, "get_models", models=[], error=str(e)
            )
