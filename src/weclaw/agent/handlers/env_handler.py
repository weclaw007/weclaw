"""环境变量和 Prompt 相关的系统消息处理器"""

import logging
import os

from weclaw.agent.handlers.base import BaseHandler, ClientContext
from weclaw.utils.env_file import find_env_file, save_env_to_file

logger = logging.getLogger(__name__)


class EnvHandler(BaseHandler):
    ACTIONS = {"save_api_key", "prompt", "save_env_list"}

    def __init__(self, websocket, ctx: ClientContext):
        super().__init__(websocket)
        self._ctx = ctx

    async def handle_prompt(self, message: dict) -> None:
        prompt = message.get("text", "")
        self._ctx.inject_prompt = prompt

    async def handle_save_api_key(self, message: dict) -> None:
        skill_name = message.get("skill_name", "")
        env_name = message.get("env_name", "")
        api_key = message.get("api_key", "")
        message_id = message.get("id", "")
        try:
            if not (env_name and api_key):
                raise ValueError("环境变量名或 API Key 为空")
            os.environ[env_name] = api_key
            save_env_to_file(find_env_file(), env_name, api_key)
            await self.send_response(message_id, "save_api_key", skill_name=skill_name, success=True)
        except Exception as e:
            await self.send_response(message_id, "save_api_key", skill_name=skill_name, success=False, error=str(e))

    async def handle_save_env_list(self, message: dict) -> None:
        skill_name = message.get("skill_name", "")
        env_list = message.get("env_list", [])
        message_id = message.get("id", "")
        try:
            if not env_list:
                raise ValueError("环境变量列表为空")
            env_path = find_env_file()
            for item in env_list:
                env_name = item.get("envName", "")
                env_value = item.get("envValue", "")
                if env_name and env_value:
                    os.environ[env_name] = env_value
                    save_env_to_file(env_path, env_name, env_value)
            await self.send_response(message_id, "save_env_list", skill_name=skill_name, success=True)
        except Exception as e:
            await self.send_response(message_id, "save_env_list", skill_name=skill_name, success=False, error=str(e))
