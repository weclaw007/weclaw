"""
CLI 安装工具模块

提供各种开发工具的自动安装函数：
- Chocolatey (Windows)
- Homebrew (macOS)
- uv (Python 包管理器)
- Node.js
- Go
"""

import platform
import subprocess
import sys

from weclaw.utils.console import (
    print_section, print_success, print_fail,
    print_detail, print_step,
)


def run_powershell_command(command: str, description: str = "") -> tuple[bool, str]:
    """
    执行PowerShell命令

    Args:
        command: PowerShell命令字符串
        description: 命令描述，用于日志输出

    Returns:
        tuple: (success, output)
    """
    if description:
        print_step(f"正在执行: {description}")

    try:
        result = subprocess.run(
            ["powershell", "-Command", command],
            capture_output=True,
            text=True,
            timeout=300  # 5分钟超时
        )

        if result.returncode == 0:
            print_success("执行成功")
            return True, result.stdout
        else:
            print_fail(f"执行失败，错误码: {result.returncode}")
            print_detail(f"错误输出: {result.stderr}")
            return False, result.stderr

    except subprocess.TimeoutExpired:
        print_fail("命令执行超时")
        return False, "命令执行超时"
    except Exception as e:
        print_fail(f"执行异常: {e}")
        return False, str(e)


def install_chocolatey() -> bool:
    """静默安装Chocolatey"""
    print_section("开始静默安装 Chocolatey")

    # 1. 设置执行策略
    print_step("1. 设置 PowerShell 执行策略...")
    execution_policy_cmd = "Set-ExecutionPolicy Bypass -Scope Process -Force"
    success, _ = run_powershell_command(execution_policy_cmd, "设置执行策略")
    if not success:
        return False

    # 2. 设置安全协议
    print_step("2. 设置安全协议...")
    security_protocol_cmd = """
    [System.Net.ServicePointManager]::SecurityProtocol = 
    [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    """
    success, _ = run_powershell_command(security_protocol_cmd, "设置安全协议")
    if not success:
        return False

    # 3. 下载并执行安装脚本
    print_step("3. 下载并执行 Chocolatey 安装脚本...")
    install_cmd = """
    iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
    """
    success, output = run_powershell_command(install_cmd, "安装Chocolatey")

    if success:
        print_success("Chocolatey 安装完成")
        return True
    else:
        print_fail("Chocolatey 安装失败")
        return False


def install_homebrew() -> bool:
    """静默安装 Homebrew (macOS)"""
    print_section("开始安装 Homebrew")

    try:
        install_cmd = '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
        result = subprocess.run(
            install_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=600,  # 10分钟超时
            env={**subprocess.os.environ, "NONINTERACTIVE": "1"}  # 非交互模式
        )

        if result.returncode == 0:
            print_success("Homebrew 安装完成")
            return True
        else:
            print_fail(f"Homebrew 安装失败: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print_fail("Homebrew 安装超时")
        return False
    except Exception as e:
        print_fail(f"Homebrew 安装异常: {e}")
        return False


def install_uv() -> bool:
    """安装 uv (Python 包管理器)"""
    print_section("开始安装 uv")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "uv"],
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode == 0:
            print_success("uv 安装完成")
            return True
        else:
            print_fail(f"uv 安装失败: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print_fail("uv 安装超时")
        return False
    except Exception as e:
        print_fail(f"uv 安装异常: {e}")
        return False


def install_node() -> bool:
    """安装 Node.js"""
    print_section("开始安装 Node.js")

    current_os = platform.system().lower()

    try:
        if current_os == "darwin":
            result = subprocess.run(
                ["brew", "install", "node"],
                capture_output=True,
                text=True,
                timeout=600
            )
        elif current_os == "windows":
            result = subprocess.run(
                ["choco", "install", "nodejs", "-y"],
                capture_output=True,
                text=True,
                timeout=600
            )
        else:
            # Linux: 使用 apt 或其他包管理器
            result = subprocess.run(
                ["sudo", "apt", "install", "-y", "nodejs", "npm"],
                capture_output=True,
                text=True,
                timeout=600
            )

        if result.returncode == 0:
            print_success("Node.js 安装完成")
            return True
        else:
            print_fail(f"Node.js 安装失败: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print_fail("Node.js 安装超时")
        return False
    except Exception as e:
        print_fail(f"Node.js 安装异常: {e}")
        return False


def install_go() -> bool:
    """安装 Go"""
    print_section("开始安装 Go")

    current_os = platform.system().lower()

    try:
        if current_os == "darwin":
            result = subprocess.run(
                ["brew", "install", "go"],
                capture_output=True,
                text=True,
                timeout=600
            )
        elif current_os == "windows":
            result = subprocess.run(
                ["choco", "install", "golang", "-y"],
                capture_output=True,
                text=True,
                timeout=600
            )
        else:
            # Linux: 使用 apt
            result = subprocess.run(
                ["sudo", "apt", "install", "-y", "golang"],
                capture_output=True,
                text=True,
                timeout=600
            )

        if result.returncode == 0:
            print_success("Go 安装完成")
            return True
        else:
            print_fail(f"Go 安装失败: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print_fail("Go 安装超时")
        return False
    except Exception as e:
        print_fail(f"Go 安装异常: {e}")
        return False
