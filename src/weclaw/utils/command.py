"""跨平台异步命令执行工具"""

import asyncio
import sys
from dataclasses import dataclass


@dataclass
class CommandResult:
    """命令执行结果"""
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def __str__(self) -> str:
        if self.ok:
            return self.stdout.strip() if self.stdout else "(success, no output)"
        return f"Error (code {self.returncode}): {self.stderr or self.stdout}".strip()


def _build_shell_cmd(command: str) -> list[str]:
    """根据操作系统构建 shell 命令"""
    if sys.platform in ("darwin", "linux") or sys.platform.startswith("linux"):
        return ["bash", "-lc", command]
    else:
        # Windows: 使用 EncodedCommand 避免 PowerShell 转义问题
        import base64
        encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
        return ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]


async def run(command: str, timeout: int = 600) -> CommandResult:
    """执行 shell 命令并捕获输出。

    Args:
        command: 要执行的命令
        timeout: 超时时间（秒），默认 600

    Returns:
        CommandResult 包含 returncode/stdout/stderr
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *_build_shell_cmd(command),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            return CommandResult(
                returncode=proc.returncode or 0,
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return CommandResult(returncode=-1, stdout="", stderr=f"命令执行超时 ({timeout}s)")
    except Exception as e:
        return CommandResult(returncode=-1, stdout="", stderr=str(e))


async def check_bins_exist(bins: list[str], extra_dirs: list[str] | None = None) -> bool:
    """检查二进制文件是否存在于 PATH 中或指定的额外目录中。"""
    from pathlib import Path

    for bin_name in bins:
        found = False
        if sys.platform == "win32":
            result = await run(f"Get-Command {bin_name} -ErrorAction SilentlyContinue")
        else:
            result = await run(f"which {bin_name}")

        if result.ok:
            found = True

        if not found and extra_dirs:
            for d in extra_dirs:
                if (Path(d) / bin_name).exists():
                    found = True
                    break

        if not found:
            return False
    return True
