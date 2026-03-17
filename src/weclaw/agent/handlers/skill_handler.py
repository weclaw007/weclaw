"""技能相关的系统消息处理器"""
import logging
import os

from weclaw.agent.handlers.base import BaseHandler
from weclaw.agent.skill_manager import SkillManager

logger = logging.getLogger(__name__)


class SkillHandler(BaseHandler):
    """处理技能管理相关的系统消息：获取列表、启用、禁用"""

    ACTIONS = {"get_skills", "enable_skill", "disable_skill"}

    async def handle_get_skills(self, message: dict) -> None:
        """处理获取技能列表消息"""
        skill_manager = SkillManager.get_instance()
        skills = skill_manager.get_skills_for_current_os()
        skills_json = []
        for skill, value in skills.items():
            env_name = value.get("metadata", {}).get("openclaw", {}).get("primaryEnv", "")
            skills_json.append({
                "name": value["name"],
                "description": value["description"],
                "emoji": value.get("metadata", {}).get("openclaw", {}).get("emoji", ""),
                "primaryEnv": os.getenv(env_name) if env_name else "",
                "envName": env_name,
                "enabled": skill_manager.is_skill_enabled(skill),
                "builtin": value.get("_builtin", True),
            })
        message_id = message.get("id", "")
        await self.send_response(message_id, "get_skills", skills=skills_json)

    async def handle_enable_skill(self, message: dict) -> None:
        """处理启用技能消息"""
        await self._toggle_skill(message, enable=True)

    async def handle_disable_skill(self, message: dict) -> None:
        """处理禁用技能消息"""
        await self._toggle_skill(message, enable=False)

    async def _toggle_skill(self, message: dict, enable: bool) -> None:
        """启用/禁用技能的通用逻辑，消除 enable_skill 和 disable_skill 的重复代码"""
        skill_name = message.get("skill_name", "")
        message_id = message.get("id", "")
        action = "enable_skill" if enable else "disable_skill"
        skill_manager = SkillManager.get_instance()

        try:
            method = skill_manager.enable_skill if enable else skill_manager.disable_skill
            success = method(skill_name)
            await self.send_response(message_id, action, skill_name=skill_name, success=success)
        except Exception as e:
            logger.exception(f"{'启用' if enable else '禁用'}技能 '{skill_name}' 失败")
            await self.send_response(
                message_id, action, skill_name=skill_name, success=False, error=str(e)
            )
