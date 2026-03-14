"""技能管理 - 底层命令执行工具函数"""

import asyncio
import sys
from typing import Any


async def run_command(command: str, timeout: int = 6000, capture: bool = False) -> dict[str, Any]:
    """执行命令行工具。
    
    参数：
        command: 要执行的命令
        timeout: 超时时间（秒）
        capture: 是否捕获输出。True 时静默执行并返回 stdout/stderr 内容；
                 False 时流式输出到终端（stdout/stderr 返回空字符串）
    """
    try:
        if sys.platform == "darwin":
            shell_cmd = ["bash", "-lc", command]
        elif sys.platform.startswith("linux"):
            shell_cmd = ["bash", "-lc", command]
        else:  # Windows
            shell_cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]

        proc = await asyncio.create_subprocess_exec(
            *shell_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        if capture:
            # 静默模式：捕获全部输出并返回
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
                return {
                    "returncode": proc.returncode or 0,
                    "stdout": stdout_bytes.decode("utf-8", errors="replace"),
                    "stderr": stderr_bytes.decode("utf-8", errors="replace"),
                }
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return {
                    "returncode": -1,
                    "stdout": "",
                    "stderr": f"命令执行超时 ({timeout}s)"
                }
        else:
            # 流式模式：实时输出到终端
            async def _stream_output(
                stream: asyncio.StreamReader | None,
                is_stderr: bool = False,
            ) -> None:
                if stream is None:
                    return

                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace")
                    if is_stderr:
                        print(text, end="", file=sys.stderr, flush=True)
                    else:
                        print(text, end="", flush=True)

            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        _stream_output(proc.stdout, is_stderr=False),
                        _stream_output(proc.stderr, is_stderr=True),
                        proc.wait(),
                    ),
                    timeout=timeout,
                )

                return {
                    "returncode": proc.returncode or 0,
                    "stdout": "",
                    "stderr": "",
                }
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return {
                    "returncode": -1,
                    "stdout": "",
                    "stderr": f"命令执行超时 ({timeout}s)"
                }
    except Exception as e:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": str(e)
        }


async def check_bins_exist(bins: list[str], extra_dirs: list[str] | None = None) -> bool:
    """检查二进制文件是否存在于 PATH 中或指定的额外目录中
    
    参数：
        bins: 需要检查的二进制文件名列表
        extra_dirs: 额外的搜索目录列表（用于检查不在 PATH 中的目录，如 GOPATH/bin）
    """
    from pathlib import Path

    for bin_name in bins:
        found = False

        # 1. 先通过 which / Get-Command 检查 PATH
        if sys.platform == "win32":
            result = await run_command(
                f"Get-Command {bin_name} -ErrorAction SilentlyContinue", capture=True
            )
        else:
            result = await run_command(f"which {bin_name}", capture=True)

        if result["returncode"] == 0:
            found = True

        # 2. 如果 PATH 中没找到，检查额外目录
        if not found and extra_dirs:
            for d in extra_dirs:
                if (Path(d) / bin_name).exists():
                    found = True
                    break

        if not found:
            return False
    return True
