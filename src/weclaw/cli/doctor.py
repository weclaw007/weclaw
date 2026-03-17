#!/usr/bin/env python3
"""
Claw 安装环境检查脚本 (doctor)

功能：
- 检查各项依赖是否已正确安装
- 输出环境诊断报告

用法：
  python doctor.py
"""

import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

from weclaw.utils.console import (
    GREEN, RED, YELLOW, CYAN, BOLD, DIM, RESET,
    colorize, print_section, print_success, print_fail,
    print_info, print_warn, print_detail, print_step,
)
from weclaw.cli.installers import (
    install_chocolatey, install_homebrew, install_uv, install_node, install_go,
)


@dataclass
class CheckResult:
    """检查结果"""
    name: str
    passed: bool
    message: str
    hint: str = ""
    auto_installed: bool = False  # 是否为自动安装成功

    @property
    def colored_message(self) -> str:
        """返回带颜色的消息"""
        if self.passed:
            if self.auto_installed:
                return f"{GREEN}✔ {self.message}{RESET}"
            else:
                return f"{GREEN}✔ {self.message}{RESET}"
        else:
            return f"{RED}✘ {self.message}{RESET}"

    @property
    def status_icon(self) -> str:
        """返回状态图标"""
        if self.passed:
            return f"{GREEN}✔{RESET}" if not self.auto_installed else f"{YELLOW}✔{RESET}"
        else:
            return f"{RED}✘{RESET}"


class Doctor:
    """环境检查器"""

    def __init__(self):
        self.results: list[CheckResult] = []

    def check_command_exists(self, cmd: str, name: str, hint: str = "") -> CheckResult:
        """检查命令是否存在于 PATH 中"""
        path = shutil.which(cmd)
        if path:
            print_success(f"{name} 已安装: {path}")
            return CheckResult(name=name, passed=True, message=f"{name} 已安装: {path}")
        else:
            print_fail(f"{name} 未找到")
            return CheckResult(name=name, passed=False, message=f"{name} 未找到", hint=hint)

    def check_command_version(self, cmd: list[str], name: str, hint: str = "") -> CheckResult:
        """检查命令版本"""
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            version = result.stdout.strip() or result.stderr.strip()
            if result.returncode == 0:
                version_line = version.splitlines()[0]
                print_success(f"{name}: {version_line}")
                return CheckResult(name=name, passed=True, message=f"{name}: {version_line}")
            else:
                print_fail(f"{name} 执行失败")
                return CheckResult(name=name, passed=False, message=f"{name} 执行失败", hint=hint)
        except FileNotFoundError:
            print_fail(f"{name} 未找到")
            return CheckResult(name=name, passed=False, message=f"{name} 未找到", hint=hint)
        except subprocess.TimeoutExpired:
            print_fail(f"{name} 执行超时")
            return CheckResult(name=name, passed=False, message=f"{name} 执行超时", hint=hint)
        except Exception as e:
            print_fail(f"{name} 检查失败: {e}")
            return CheckResult(name=name, passed=False, message=f"{name} 检查失败: {e}", hint=hint)

    def check_python(self) -> CheckResult:
        """检查 Python 版本 (>= 3.10)"""
        name = "Python"
        print(f"\n  {BOLD}● 正在检查 {name}...{RESET}")
        required = (3, 10)
        current = sys.version_info[:2]
        version_str = f"{current[0]}.{current[1]}"
        print_detail(f"检测到版本: {version_str}")
        print_detail(f"要求版本:   >= {required[0]}.{required[1]}")

        if current >= required:
            print_success(f"版本满足要求")
            return CheckResult(
                name=name,
                passed=True,
                message=f"{name}: {version_str} (>= {required[0]}.{required[1]})"
            )
        else:
            print_fail(f"版本不满足要求")
            return CheckResult(
                name=name,
                passed=False,
                message=f"{name}: {version_str} (需要 >= {required[0]}.{required[1]})",
                hint="请安装 Python 3.10 或更高版本: https://www.python.org/downloads/"
            )

    def check_chocolatey(self) -> CheckResult:
        """检查 Chocolatey 是否已安装 (仅 Windows)，未安装则自动安装"""
        name = "Chocolatey"
        print(f"\n  {BOLD}● 正在检查 {name}...{RESET}")

        # 检查 choco 命令是否存在
        choco_path = shutil.which("choco")
        if choco_path:
            print_detail(f"找到命令: {choco_path}")
            # 获取版本
            try:
                result = subprocess.run(
                    ["choco", "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                version = result.stdout.strip()
                print_detail(f"检测到版本: {version}")
                print_success("已安装")
                return CheckResult(
                    name=name,
                    passed=True,
                    message=f"{name}: {version} ({choco_path})"
                )
            except Exception:
                print_success("已安装")
                return CheckResult(
                    name=name,
                    passed=True,
                    message=f"{name} 已安装: {choco_path}"
                )

        # 未安装，尝试自动安装
        print_fail("未找到")
        print_warn(f"正在自动安装 {name}...")
        try:
            success = install_chocolatey()
            if success:
                print_success(f"{name} 自动安装成功")
                return CheckResult(
                    name=name,
                    passed=True,
                    message=f"{name}: 已自动安装成功",
                    auto_installed=True
                )
            else:
                print_fail(f"{name} 自动安装失败")
                return CheckResult(
                    name=name,
                    passed=False,
                    message=f"{name}: 自动安装失败",
                    hint="请以管理员权限运行或手动安装: https://chocolatey.org/install"
                )
        except Exception as e:
            print_fail(f"{name} 自动安装失败 ({e})")
            return CheckResult(
                name=name,
                passed=False,
                message=f"{name}: 自动安装失败 ({e})",
                hint="请以管理员权限运行或手动安装: https://chocolatey.org/install"
            )

    def check_homebrew(self) -> CheckResult:
        """检查 Homebrew 是否已安装 (仅 macOS)，未安装则自动安装"""
        name = "Homebrew"
        print(f"\n  {BOLD}● 正在检查 {name}...{RESET}")

        # 检查 brew 命令是否存在
        brew_path = shutil.which("brew")
        if brew_path:
            print_detail(f"找到命令: {brew_path}")
            # 获取版本
            try:
                result = subprocess.run(
                    ["brew", "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                version = result.stdout.strip().splitlines()[0] if result.stdout else ""
                print_detail(f"检测到版本: {version}")
                print_success("已安装")
                return CheckResult(
                    name=name,
                    passed=True,
                    message=f"{name}: {version}"
                )
            except Exception:
                print_success("已安装")
                return CheckResult(
                    name=name,
                    passed=True,
                    message=f"{name} 已安装: {brew_path}"
                )

        # 未安装，尝试自动安装
        print_fail("未找到")
        print_warn(f"正在自动安装 {name}...")
        try:
            success = install_homebrew()
            if success:
                print_success(f"{name} 自动安装成功")
                return CheckResult(
                    name=name,
                    passed=True,
                    message=f"{name}: 已自动安装成功",
                    auto_installed=True
                )
            else:
                print_fail(f"{name} 自动安装失败")
                return CheckResult(
                    name=name,
                    passed=False,
                    message=f"{name}: 自动安装失败",
                    hint="请手动安装: https://brew.sh"
                )
        except Exception as e:
            print_fail(f"{name} 自动安装失败 ({e})")
            return CheckResult(
                name=name,
                passed=False,
                message=f"{name}: 自动安装失败 ({e})",
                hint="请手动安装: https://brew.sh"
            )

    def check_uv(self) -> CheckResult:
        """检查 uv 是否已安装，未安装则自动安装"""
        name = "uv"
        print(f"\n  {BOLD}● 正在检查 {name}...{RESET}")

        # 检查 uv 命令是否存在
        uv_path = shutil.which("uv")
        if uv_path:
            print_detail(f"找到命令: {uv_path}")
            # 获取版本
            try:
                result = subprocess.run(
                    ["uv", "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                version = result.stdout.strip()
                print_detail(f"检测到版本: {version}")
                print_success("已安装")
                return CheckResult(
                    name=name,
                    passed=True,
                    message=f"{name}: {version}"
                )
            except Exception:
                print_success("已安装")
                return CheckResult(
                    name=name,
                    passed=True,
                    message=f"{name} 已安装: {uv_path}"
                )

        # 未安装，尝试自动安装
        print_fail("未找到")
        print_warn(f"正在自动安装 {name}...")
        try:
            success = install_uv()
            if success:
                print_success(f"{name} 自动安装成功")
                return CheckResult(
                    name=name,
                    passed=True,
                    message=f"{name}: 已自动安装成功",
                    auto_installed=True
                )
            else:
                print_fail(f"{name} 自动安装失败")
                return CheckResult(
                    name=name,
                    passed=False,
                    message=f"{name}: 自动安装失败",
                    hint="请手动安装: https://docs.astral.sh/uv/getting-started/installation/"
                )
        except Exception as e:
            print_fail(f"{name} 自动安装失败 ({e})")
            return CheckResult(
                name=name,
                passed=False,
                message=f"{name}: 自动安装失败 ({e})",
                hint="请手动安装: https://docs.astral.sh/uv/getting-started/installation/"
            )

    def check_node(self) -> CheckResult:
        """检查 Node.js 是否已安装，未安装则自动安装"""
        name = "Node.js"
        print(f"\n  {BOLD}● 正在检查 {name}...{RESET}")

        # 检查 node 命令是否存在
        node_path = shutil.which("node")
        if node_path:
            print_detail(f"找到命令: {node_path}")
            try:
                result = subprocess.run(
                    ["node", "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                version = result.stdout.strip()
                print_detail(f"检测到版本: {version}")
                print_success("已安装")
                return CheckResult(
                    name=name,
                    passed=True,
                    message=f"{name}: {version}"
                )
            except Exception:
                print_success("已安装")
                return CheckResult(
                    name=name,
                    passed=True,
                    message=f"{name} 已安装: {node_path}"
                )

        # 未安装，尝试自动安装
        print_fail("未找到")
        print_warn(f"正在自动安装 {name}...")
        try:
            success = install_node()
            if success:
                print_success(f"{name} 自动安装成功")
                return CheckResult(
                    name=name,
                    passed=True,
                    message=f"{name}: 已自动安装成功",
                    auto_installed=True
                )
            else:
                print_fail(f"{name} 自动安装失败")
                return CheckResult(
                    name=name,
                    passed=False,
                    message=f"{name}: 自动安装失败",
                    hint="请手动安装: https://nodejs.org/"
                )
        except Exception as e:
            print_fail(f"{name} 自动安装失败 ({e})")
            return CheckResult(
                name=name,
                passed=False,
                message=f"{name}: 自动安装失败 ({e})",
                hint="请手动安装: https://nodejs.org/"
            )

    def check_go(self) -> CheckResult:
        """检查 Go 是否已安装，未安装则自动安装"""
        name = "Go"
        print(f"\n  {BOLD}● 正在检查 {name}...{RESET}")

        # 检查 go 命令是否存在
        go_path = shutil.which("go")
        if go_path:
            print_detail(f"找到命令: {go_path}")
            try:
                result = subprocess.run(
                    ["go", "version"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                version = result.stdout.strip()
                print_detail(f"检测到版本: {version}")
                print_success("已安装")
                return CheckResult(
                    name=name,
                    passed=True,
                    message=f"{name}: {version}"
                )
            except Exception:
                print_success("已安装")
                return CheckResult(
                    name=name,
                    passed=True,
                    message=f"{name} 已安装: {go_path}"
                )

        # 未安装，尝试自动安装
        print_fail("未找到")
        print_warn(f"正在自动安装 {name}...")
        try:
            success = install_go()
            if success:
                print_success(f"{name} 自动安装成功")
                return CheckResult(
                    name=name,
                    passed=True,
                    message=f"{name}: 已自动安装成功",
                    auto_installed=True
                )
            else:
                print_fail(f"{name} 自动安装失败")
                return CheckResult(
                    name=name,
                    passed=False,
                    message=f"{name}: 自动安装失败",
                    hint="请手动安装: https://go.dev/dl/"
                )
        except Exception as e:
            print_fail(f"{name} 自动安装失败 ({e})")
            return CheckResult(
                name=name,
                passed=False,
                message=f"{name}: 自动安装失败 ({e})",
                hint="请手动安装: https://go.dev/dl/"
            )

    def check_go_path(self) -> CheckResult:
        """检查 GOPATH/bin 是否在 PATH 中，未配置则自动添加到 shell 配置文件"""
        name = "Go PATH"
        print(f"\n  {BOLD}● 正在检查 {name}...{RESET}")

        # 获取 GOPATH/bin 或 GOBIN 目录
        go_bin_dir = self._get_go_bin_dir()
        if not go_bin_dir:
            print_detail("无法获取 Go bin 目录，跳过检查")
            return CheckResult(
                name=name,
                passed=True,
                message=f"{name}: 跳过（未安装 Go 或无法获取 GOPATH）"
            )

        print_detail(f"Go bin 目录: {go_bin_dir}")

        # 检查是否已在 PATH 中
        import os
        path_dirs = os.environ.get("PATH", "").split(os.pathsep)
        # 标准化路径进行比较
        go_bin_resolved = os.path.realpath(os.path.expanduser(go_bin_dir))
        in_path = any(
            os.path.realpath(os.path.expanduser(d)) == go_bin_resolved
            for d in path_dirs if d
        )

        if in_path:
            print_success(f"Go bin 目录已在 PATH 中: {go_bin_dir}")
            return CheckResult(
                name=name,
                passed=True,
                message=f"{name}: {go_bin_dir} 已在 PATH 中"
            )

        # 未在 PATH 中，尝试自动修复
        print_fail(f"Go bin 目录不在 PATH 中: {go_bin_dir}")
        print_warn("正在自动添加到 shell 配置文件...")

        fix_result = self._fix_go_path(go_bin_dir)
        if fix_result:
            # 同时更新当前进程的 PATH，使后续操作立即生效
            os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + go_bin_dir
            if fix_result == "written":
                # 实际写入了配置文件，标记为自动安装
                print_success(f"已自动添加到 shell 配置文件并更新当前环境")
                return CheckResult(
                    name=name,
                    passed=True,
                    message=f"{name}: 已自动将 {go_bin_dir} 添加到 PATH",
                    auto_installed=True
                )
            else:
                # 配置已存在，只是当前 shell 未生效，仅更新当前进程 PATH
                print_success(f"shell 配置文件中已有配置，已更新当前环境")
                return CheckResult(
                    name=name,
                    passed=True,
                    message=f"{name}: {go_bin_dir} 已配置（已更新当前环境）"
                )
        else:
            return CheckResult(
                name=name,
                passed=False,
                message=f"{name}: {go_bin_dir} 不在 PATH 中，自动修复失败",
                hint=f'请手动在 shell 配置文件中添加: export PATH="$PATH:{go_bin_dir}"'
            )

    def _get_go_bin_dir(self) -> str:
        """获取 Go 的 bin 目录路径"""
        import os

        go_path = shutil.which("go")
        if not go_path:
            return ""

        try:
            # 优先使用 GOBIN
            result = subprocess.run(
                ["go", "env", "GOBIN"],
                capture_output=True, text=True, timeout=10
            )
            gobin = result.stdout.strip()
            if gobin:
                return gobin

            # 其次使用 GOPATH/bin
            result = subprocess.run(
                ["go", "env", "GOPATH"],
                capture_output=True, text=True, timeout=10
            )
            gopath = result.stdout.strip()
            if gopath:
                return os.path.join(gopath, "bin")
        except Exception:
            pass

        # 兜底：使用默认路径 ~/go/bin
        return os.path.expanduser("~/go/bin")

    def _fix_go_path(self, go_bin_dir: str) -> str:
        """将 Go bin 目录添加到 shell 配置文件的 PATH 中
        
        Returns:
            "written": 实际写入了配置文件
            "exists": 配置已存在，跳过写入
            "": 修复失败
        """
        import os

        current_os = platform.system().lower()
        home = os.path.expanduser("~")

        # 使用 $HOME/go/bin 格式（更通用），如果路径恰好是 ~/go/bin
        home_resolved = os.path.realpath(home)
        go_bin_resolved = os.path.realpath(go_bin_dir)
        if go_bin_resolved.startswith(home_resolved):
            # 用 $HOME 替换实际 home 路径，使配置更具可移植性
            export_path = go_bin_resolved.replace(home_resolved, "$HOME", 1)
        else:
            export_path = go_bin_dir

        export_line = f'export PATH="$PATH:{export_path}"'

        # 确定 shell 配置文件
        if current_os == "darwin":
            # macOS: 优先 ~/.zshrc（默认 shell 是 zsh）
            shell = os.environ.get("SHELL", "")
            if "zsh" in shell:
                rc_file = os.path.join(home, ".zshrc")
            elif "bash" in shell:
                rc_file = os.path.join(home, ".bash_profile")
            else:
                rc_file = os.path.join(home, ".zshrc")
        elif current_os == "linux":
            shell = os.environ.get("SHELL", "")
            if "zsh" in shell:
                rc_file = os.path.join(home, ".zshrc")
            else:
                rc_file = os.path.join(home, ".bashrc")
        else:
            # Windows 不通过此方式处理
            print_warn("Windows 系统请手动配置环境变量")
            return False

        try:
            # 先检查是否已经存在类似的配置
            if os.path.exists(rc_file):
                with open(rc_file, "r") as f:
                    content = f.read()
                # 检查是否已有 go/bin 相关的 PATH 配置
                if "go/bin" in content and "PATH" in content:
                    print_detail(f"检测到 {rc_file} 中已存在 go/bin 的 PATH 配置，跳过写入")
                    # 配置已存在但当前 shell 未生效
                    return "exists"

            # 追加配置到文件末尾
            with open(rc_file, "a") as f:
                f.write(f"\n# Go bin 目录（由 claw doctor 自动添加）\n")
                f.write(f"{export_line}\n")

            print_detail(f"已写入: {rc_file}")
            print_info(f"💡 新终端窗口将自动生效，或执行: source {rc_file}")
            return "written"

        except PermissionError:
            print_fail(f"无权限写入 {rc_file}")
            return ""
        except Exception as e:
            print_fail(f"写入 {rc_file} 失败: {e}")
            return ""

    def run_all_checks(self) -> list[CheckResult]:
        """运行所有检查"""
        self.results = []
        self.results.append(self.check_python())

        current_os = platform.system().lower()

        # Windows 系统检查 Chocolatey
        if current_os == "windows":
            self.results.append(self.check_chocolatey())

        # macOS 系统检查 Homebrew
        if current_os == "darwin":
            self.results.append(self.check_homebrew())

        # 所有系统检查 uv, Node.js, Go
        self.results.append(self.check_uv())
        self.results.append(self.check_node())
        self.results.append(self.check_go())

        # Go 已安装时，检查 GOPATH/bin 是否在 PATH 中
        go_result = self.results[-1]  # 最后一个是 check_go 的结果
        if go_result.passed:
            self.results.append(self.check_go_path())

        return self.results

    def print_report(self) -> int:
        """打印诊断报告，返回退出码"""
        print_section("🩺 Claw 环境检查报告")

        if not self.results:
            print_warn("暂无检查项")
            return 0

        passed = 0
        failed = 0
        auto_installed = 0

        for result in self.results:
            # 使用彩色状态图标 + 消息
            print(f"  {result.status_icon} {result.message}")
            if result.hint and not result.passed:
                print(f"    {YELLOW}💡 提示: {result.hint}{RESET}")
            if result.passed:
                passed += 1
                if result.auto_installed:
                    auto_installed += 1
            else:
                failed += 1

        # ── 汇总统计 ──
        print(f"\n  {BOLD}{'─' * 40}{RESET}")
        total = passed + failed
        # 通过数显示绿色，失败数显示红色
        summary_parts = []
        summary_parts.append(f"{GREEN}{passed} 项通过{RESET}")
        if auto_installed > 0:
            summary_parts.append(f"{YELLOW}{auto_installed} 项自动安装{RESET}")
        if failed > 0:
            summary_parts.append(f"{RED}{failed} 项失败{RESET}")
        else:
            summary_parts.append(f"{GREEN}0 项失败{RESET}")

        print(f"  {BOLD}检查完成{RESET}: 共 {total} 项 | {' | '.join(summary_parts)}")

        if failed == 0:
            print(f"\n  {GREEN}{BOLD}🎉 所有检查均已通过，环境准备就绪！{RESET}")
        else:
            print(f"\n  {RED}{BOLD}⚠ 有 {failed} 项检查未通过，请根据提示修复后重试{RESET}")

        print()
        return 0 if failed == 0 else 1


def main() -> int:
    """主函数"""
    print_section("🩺 Claw 环境诊断 (doctor)")
    print_info(f"操作系统: {platform.system()} {platform.release()}")
    print_info(f"Python:   {sys.version.split()[0]}")
    print()

    doctor = Doctor()
    doctor.run_all_checks()
    return doctor.print_report()


if __name__ == "__main__":
    sys.exit(main())
