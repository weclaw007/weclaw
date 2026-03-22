"""环境变量和 Prompt 相关的系统消息处理器"""
import logging
import os

from weclaw.agent.handlers.base import BaseHandler, ClientContext
from weclaw.utils.env_file import find_env_file, save_env_to_file

logger = logging.getLogger(__name__)


class EnvHandler(BaseHandler):
    """处理环境配置相关的系统消息：保存 API Key、设置 Prompt"""

    ACTIONS = {"save_api_key", "prompt", "save_env_list"}

    def __init__(self, websocket, ctx: ClientContext):
        super().__init__(websocket)
        self._ctx = ctx

    async def handle_prompt(self, message: dict) -> None:
        """处理系统消息（prompt），注入到下次 Agent 初始化"""
        prompt = message.get("text", "")
        logger.info(f"处理 prompt 消息: {prompt}")
        self._ctx.inject_prompt = prompt

    async def handle_save_api_key(self, message: dict) -> None:
        """处理保存 API Key 消息，同时写入内存环境变量和 .env 文件"""
        skill_name = message.get("skill_name", "")
        env_name = message.get("env_name", "")
        api_key = message.get("api_key", "")
        message_id = message.get("id", "")

        try:
            if not (env_name and api_key):
                raise ValueError("环境变量名或 API Key 为空")

            # 1. 设置内存中的环境变量（立即生效）
            os.environ[env_name] = api_key
            # 2. 持久化写入 .env 文件（重启后仍生效）
            env_path = find_env_file()
            save_env_to_file(env_path, env_name, api_key)
            logger.info(f"已保存 API Key: 技能={skill_name}, 环境变量={env_name}, 文件={env_path}")
            await self.send_response(
                message_id, "save_api_key", skill_name=skill_name, success=True
            )
        except Exception as e:
            logger.exception(f"保存 API Key 失败: 技能={skill_name}")
            await self.send_response(
                message_id, "save_api_key", skill_name=skill_name, success=False, error=str(e)
            )

    async def handle_save_env_list(self, message: dict) -> None:
        """处理批量保存环境变量消息，支持一次性保存多个环境变量到内存和 .env 文件"""
        skill_name = message.get("skill_name", "")
        env_list = message.get("env_list", [])  # [{"envName": "xxx", "envValue": "xxx"}, ...]
        message_id = message.get("id", "")

        try:
            if not env_list:
                raise ValueError("环境变量列表为空")

            env_path = find_env_file()
            saved_keys = []
            for item in env_list:
                env_name = item.get("envName", "")
                env_value = item.get("envValue", "")
                if env_name and env_value:
                    # 1. 设置内存中的环境变量（立即生效）
                    os.environ[env_name] = env_value
                    # 2. 持久化写入 .env 文件（重启后仍生效）
                    save_env_to_file(env_path, env_name, env_value)
                    saved_keys.append(env_name)

            logger.info(f"已批量保存环境变量: 技能={skill_name}, 变量={saved_keys}, 文件={env_path}")
            await self.send_response(
                message_id, "save_env_list", skill_name=skill_name, success=True
            )
        except Exception as e:
            logger.exception(f"批量保存环境变量失败: 技能={skill_name}")
            await self.send_response(
                message_id, "save_env_list", skill_name=skill_name, success=False, error=str(e)
            )
