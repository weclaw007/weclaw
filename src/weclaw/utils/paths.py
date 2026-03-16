"""weclaw 路径工具函数 - 统一管理 weclaw 的各类保存目录"""

from pathlib import Path


def get_data_dir() -> Path:
    """获取 weclaw 的数据保存根目录。

    默认为 ~/.weclaw。
    如果目录不存在会自动创建。

    Returns:
        Path: 数据保存根目录的绝对路径
    """
    data_dir = Path.home() / ".weclaw"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_session_dir(session_id: str = "main") -> Path:
    """获取指定会话的数据目录。

    默认为 <data_dir>/sessions/<session_id>。
    如果目录不存在会自动创建。

    Args:
        session_id: 会话 ID，默认为 "main"

    Returns:
        Path: 会话数据目录的绝对路径
    """
    session_dir = get_data_dir() / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def get_checkpoint_db_path(session_id: str = "main") -> str:
    """获取指定会话的 checkpoint 数据库文件路径。

    默认为 <data_dir>/sessions/<session_id>/checkpoint.db。

    Args:
        session_id: 会话 ID，默认为 "main"

    Returns:
        str: checkpoint 数据库文件的绝对路径字符串
    """
    return str(get_session_dir(session_id) / "checkpoint.db")


def get_third_party_skills_dir() -> Path:
    """获取第三方技能文件目录。

    默认为 <data_dir>/skills。

    Returns:
        Path: 第三方技能文件目录的绝对路径
    """
    return get_data_dir() / "skills"


def get_config_file_path() -> Path:
    """获取技能配置文件路径。

    默认为 <data_dir>/config.yaml。

    Returns:
        Path: 配置文件的绝对路径
    """
    return get_data_dir() / "config.yaml"


def get_tool_archive_dir(session_id: str = "main") -> Path:
    """获取指定会话的工具结果归档目录。

    默认为 <data_dir>/sessions/<session_id>/tool_archive。
    如果目录不存在会自动创建。

    Args:
        session_id: 会话 ID，默认为 "main"

    Returns:
        Path: 工具结果归档目录的绝对路径
    """
    archive_dir = get_session_dir(session_id) / "tool_archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    return archive_dir
