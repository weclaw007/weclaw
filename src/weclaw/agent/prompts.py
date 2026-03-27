"""系统提示词构建模块

技能相关的提示词由 SkillsMiddleware 自动注入，此处只负责角色定义和环境信息。
"""

import platform
from datetime import datetime

from weclaw.utils.agent_config import AgentConfig


def build_system_prompt(
    agent_config: AgentConfig | None = None,
) -> str:
    """构建完整的系统提示词。

    结构：
    1. 角色定义 + 人格（可选）
    2. 环境信息（时间、平台）

    注意：技能列表和使用指南由 SkillsMiddleware 在 Agent 初始化时自动注入，
    不再需要在此处手动拼接。
    """
    parts: list[str] = []

    # ── 1. 角色定义 ──
    parts.append(
        "You are a helpful AI assistant with access to various tools and skills. "
    )

    if agent_config and agent_config.persona:
        parts.append(f"\n## Persona\n{agent_config.persona}")

    # ── 2. 环境信息 ──
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
    os_info = f"{platform.system()} {platform.release()}"
    parts.append(
        f"\n## Environment\n"
        f"- Current time: {now_str}\n"
        f"- Operating system: {os_info}"
    )

    return "\n".join(parts)
