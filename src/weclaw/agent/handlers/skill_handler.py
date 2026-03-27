"""技能相关的系统消息处理器"""

import logging
import os

from weclaw.agent.handlers.base import BaseHandler
from weclaw.skill_mgr.manager import SkillManager

logger = logging.getLogger(__name__)


class SkillHandler(BaseHandler):
    ACTIONS = {"get_skills", "enable_skill", "disable_skill"}

    async def handle_get_skills(self, message: dict) -> None:
        skill_manager = SkillManager.get_instance()
        skills = skill_manager.get_skills_for_current_os()
        skills_json = []
        for skill, value in skills.items():
            openclaw = value.get("metadata", {}).get("openclaw", {})
            env_keys = openclaw.get("requires", {}).get("env", [])
            primary_env = openclaw.get("primaryEnv", "")
            if primary_env and primary_env not in env_keys:
                env_keys = [primary_env] + list(env_keys)
            env_list = [{"envName": k, "envValue": os.getenv(k, "")} for k in env_keys]
            skills_json.append({
                "name": value["name"],
                "description": value["description"],
                "emoji": openclaw.get("emoji", ""),
                "envList": env_list,
                "enabled": skill_manager.is_skill_enabled(skill),
                "builtin": value.get("_builtin", True),
            })
        await self.send_response(message.get("id", ""), "get_skills", skills=skills_json)

    async def handle_enable_skill(self, message: dict) -> None:
        await self._toggle_skill(message, enable=True)

    async def handle_disable_skill(self, message: dict) -> None:
        await self._toggle_skill(message, enable=False)

    async def _toggle_skill(self, message: dict, enable: bool) -> None:
        skill_name = message.get("skill_name", "")
        message_id = message.get("id", "")
        action = "enable_skill" if enable else "disable_skill"
        skill_manager = SkillManager.get_instance()
        try:
            method = skill_manager.enable_skill if enable else skill_manager.disable_skill
            success = method(skill_name)
            if success:
                # 重建 active_skills symlink 目录，使新会话感知变化
                skill_manager.rebuild_active_skills_dir()
            await self.send_response(message_id, action, skill_name=skill_name, success=success)
        except Exception as e:
            await self.send_response(message_id, action, skill_name=skill_name, success=False, error=str(e))
