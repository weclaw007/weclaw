"""环境变量文件读写工具

从 Client 类中提取的 .env 文件操作函数，便于跨模块复用。
"""
from pathlib import Path


def find_env_file() -> str:
    """查找 .env 文件路径，使用 dotenv 的 find_dotenv 定位"""
    try:
        from dotenv import find_dotenv
        env_path = find_dotenv(usecwd=True)
        if env_path:
            return env_path
    except ImportError:
        pass
    # 回退：从当前文件向上查找包含 .env 的目录
    current = Path(__file__).resolve().parent
    for _ in range(10):
        candidate = current / ".env"
        if candidate.exists():
            return str(candidate)
        parent = current.parent
        if parent == current:
            break
        current = parent
    # 如果找不到，默认在项目根目录创建
    return str(Path(__file__).resolve().parent.parent.parent / ".env")


def save_env_to_file(env_path: str, env_name: str, api_key: str) -> None:
    """将环境变量写入 .env 文件（更新已有的或追加新的）"""
    env_file = Path(env_path)
    lines = []
    found = False

    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # 查找并替换已有的同名变量
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"{env_name}=") or stripped.startswith(f"{env_name} ="):
                lines[i] = f"{env_name}={api_key}\n"
                found = True
                break

    if not found:
        # 追加新的环境变量
        if lines and not lines[-1].endswith("\n"):
            lines.append("\n")
        lines.append(f"{env_name}={api_key}\n")

    with open(env_file, "w", encoding="utf-8") as f:
        f.writelines(lines)
