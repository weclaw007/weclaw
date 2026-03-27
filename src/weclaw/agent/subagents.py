"""子智能体定义

改造说明：原 skill_executor 子智能体已移除。
技能执行改由 SkillsMiddleware 注入技能列表到主 Agent 的 system prompt，
主 Agent 直接通过内置 read_file + execute 工具完成技能调用。
"""

from deepagents.middleware.subagents import SubAgent


def get_subagents_config() -> list[SubAgent]:
    """返回子智能体配置列表。

    当前无自定义子智能体（技能执行由 SkillsMiddleware + 主 Agent 完成）。
    保留此函数以便将来添加其他子智能体。

    Returns:
        DeepAgents create_deep_agent 的 subagents 参数
    """
    return []
