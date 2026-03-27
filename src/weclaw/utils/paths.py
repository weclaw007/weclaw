"""weclaw 路径工具函数 - 统一管理 weclaw 的各类保存目录"""

from pathlib import Path


def get_data_dir() -> Path:
    """获取 weclaw 的数据保存根目录 (~/.weclaw)，不存在则自动创建。"""
    data_dir = Path.home() / ".weclaw"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_session_dir(session_id: str = "main") -> Path:
    """获取指定会话的数据目录，不存在则自动创建。"""
    session_dir = get_data_dir() / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def get_checkpoint_db_path(session_id: str = "main") -> str:
    """获取指定会话的 checkpoint 数据库文件路径。"""
    return str(get_session_dir(session_id) / "checkpoint.db")


def get_third_party_skills_dir() -> Path:
    """获取第三方技能文件目录 (~/.weclaw/skills)。"""
    return get_data_dir() / "skills"


def get_config_file_path() -> Path:
    """获取技能配置文件路径 (~/.weclaw/config.yaml)。"""
    return get_data_dir() / "config.yaml"


def get_jobs_db_path(session_id: str = "main") -> str:
    """获取指定会话的定时任务数据库文件路径。"""
    return str(get_session_dir(session_id) / "jobs.db")


def get_active_skills_dir() -> Path:
    """获取运行时激活技能的 symlink 目录 (~/.weclaw/active_skills/)。

    SkillsMiddleware 扫描此目录下的 */SKILL.md，
    只有启用且 OS 兼容的技能才会被 symlink 到这里。
    """
    return get_data_dir() / "active_skills"
