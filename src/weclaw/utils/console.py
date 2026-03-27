"""终端输出工具 - 统一的彩色打印和格式化输出"""

# ── 终端颜色常量 ──
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def colorize(text: str, color: str) -> str:
    """给文本包裹颜色"""
    return f"{color}{text}{RESET}"


def print_section(title: str) -> None:
    """打印分隔标题"""
    print(f"\n{BOLD}{CYAN}{'═' * 60}")
    print(f"  {title}")
    print(f"{'═' * 60}{RESET}")


def print_success(msg: str) -> None:
    print(f"  {GREEN}✔ {msg}{RESET}")


def print_fail(msg: str) -> None:
    print(f"  {RED}✘ {msg}{RESET}")


def print_info(msg: str) -> None:
    print(f"  {CYAN}ℹ {msg}{RESET}")


def print_warn(msg: str) -> None:
    print(f"  {YELLOW}⚠ {msg}{RESET}")


def print_detail(msg: str) -> None:
    print(f"    {DIM}{msg}{RESET}")


def print_step(msg: str) -> None:
    print(f"  {CYAN}→{RESET} {msg}")


def format_duration(seconds: float) -> str:
    """格式化耗时显示"""
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.1f}s"
    else:
        m, s = divmod(int(seconds), 60)
        return f"{m}m{s}s"
