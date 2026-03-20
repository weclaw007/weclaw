"""技能管理 - 底层命令执行工具函数"""

import asyncio
import sys
from typing import Any


def _escape_powershell_command(command: str) -> str:
    """对 PowerShell 命令中的特殊字符进行转义处理。

    PowerShell 通过 -Command 参数接收命令时，双引号会被 shell 解释器消耗。
    此函数将命令用 Base64 编码后通过 -EncodedCommand 参数传递，
    彻底规避 PowerShell 对引号、$符号等特殊字符的解释问题。
    """
    import base64
    # PowerShell -EncodedCommand 要求 UTF-16LE 编码的 Base64 字符串
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    return encoded


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
            # 使用 -EncodedCommand 传递 Base64 编码的命令，
            # 彻底避免 PowerShell 对双引号、$符号等特殊字符的转义问题
            encoded = _escape_powershell_command(command)
            shell_cmd = ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]

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
