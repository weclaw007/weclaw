"""技能管理 - 安装/卸载/状态检查模块

v2 变更：
- 从 agent/skill_operations.py 迁移到 skills/operations.py
- 适配 v2 command.run() 返回 CommandResult（dataclass，.ok 属性）
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any

from weclaw.utils.command import run, check_bins_exist


def _filter_install_list(install_list: list[dict], current_platform: str) -> list[dict]:
    """根据当前操作系统过滤安装方法列表"""
    filtered = []
    for install_item in install_list:
        kind = install_item.get("kind", "")
        if kind == "brew" and current_platform == "darwin":
            filtered.append(install_item)
        elif kind == "apt" and current_platform == "linux":
            filtered.append(install_item)
        elif kind == "choco" and current_platform == "win32":
            filtered.append(install_item)
        elif kind not in ["brew", "apt", "choco"]:
            filtered.append(install_item)
    return filtered


# ============================================================
# 通用辅助函数：消除安装/卸载的重复代码
# ============================================================

async def _run_install_command(command: str) -> dict[str, Any]:
    """执行安装/卸载命令并返回标准化结果。"""
    result = await run(command)
    return {
        "success": result.ok,
        "output": result.stdout or "",
        "error": result.stderr if not result.ok else None,
    }


async def _run_pkg_command(install_item: dict[str, Any], pkg_field: str, cmd_template: str) -> dict[str, Any]:
    """通用包管理命令：从 install_item 读取包名，填入命令模板执行。

    同时用于安装和卸载场景。
    """
    package = install_item.get(pkg_field, "")
    if not package:
        return {"success": False, "error": f"缺少 {pkg_field} 字段"}
    try:
        return await _run_install_command(cmd_template.format(pkg=package))
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================
# 状态检查
# ============================================================

async def check_skills_installed(skill_metadata: dict[str, Any]) -> bool:
    """检查指定的技能是否已安装。

    判断 openclaw.requires.bins 中要求的二进制文件是否存在于 PATH 中，
    以及 openclaw.requires.env 中要求的环境变量是否已设置。
    如果没有定义 requires，则视为已安装（无外部依赖）。
    """
    if not skill_metadata:
        return False

    openclaw = skill_metadata.get("metadata", {}).get("openclaw", {})
    requires = openclaw.get("requires", {})
    bins = requires.get("bins", [])
    env_keys = requires.get("env", [])

    # 检查 requires.env 中要求的环境变量是否已设置
    if env_keys:
        for key in env_keys:
            if not os.environ.get(key):
                return False

    # 如果没有定义 requires.bins，视为无外部二进制依赖
    if not bins:
        return True

    # 收集安装类型对应的额外 bin 目录
    install_list = openclaw.get("install", [])
    extra_dirs: list[str] = []
    for install_item in install_list:
        kind = install_item.get("kind", "")
        dirs = await _get_extra_bin_dirs(kind)
        extra_dirs.extend(dirs)

    return await check_bins_exist(bins, extra_dirs=extra_dirs)


# ============================================================
# 安装
# ============================================================

async def install_skills(skill_metadata_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """安装指定的技能。

    参数：
        skill_metadata_map: {skill_name: front_matter} 字典

    返回结构：
    {
        "success": True/False,
        "skill_names": list[str],
        "install_results": [{...}],
        "error": str | None
    }
    """
    if not skill_metadata_map:
        return {"success": False, "skill_names": [], "error": "未提供技能信息"}

    install_results = []
    all_success = True

    for skill_name, metadata in skill_metadata_map.items():
        # 检查操作系统兼容性
        openclaw = metadata.get("metadata", {}).get("openclaw", {})
        required_os = openclaw.get("os", [])

        if required_os and sys.platform not in required_os:
            install_results.append({
                "skill_name": skill_name,
                "success": False,
                "error": f"技能 '{skill_name}' 要求操作系统 {required_os}，但当前系统为 {sys.platform}",
            })
            all_success = False
            continue

        install_list = openclaw.get("install", [])
        if not install_list:
            install_results.append({
                "skill_name": skill_name,
                "success": False,
                "error": f"技能 '{skill_name}' 没有定义 openclaw.install 安装方法",
            })
            all_success = False
            continue

        current_platform = sys.platform
        filtered_install_list = _filter_install_list(install_list, current_platform)

        if not filtered_install_list:
            install_results.append({
                "skill_name": skill_name,
                "success": False,
                "error": f"技能 '{skill_name}' 在当前操作系统 {current_platform} 下没有可用的安装方法",
            })
            all_success = False
            continue

        # 执行过滤后的安装方法
        install_methods = []
        skill_success = True

        for install_item in filtered_install_list:
            install_id = install_item.get("id", "unknown")
            kind = install_item.get("kind", "")
            result = await _execute_install(skill_name, install_item)
            install_methods.append({
                "id": install_id,
                "kind": kind,
                "status": "success" if result["success"] else "failed",
                "output": result.get("output", ""),
                "error": result.get("error"),
            })
            if not result["success"]:
                skill_success = False

        install_results.append({
            "skill_name": skill_name,
            "success": skill_success,
            "install_methods": install_methods,
            "error": None if skill_success else "部分或全部安装方法执行失败",
        })
        if not skill_success:
            all_success = False

    return {
        "success": all_success,
        "skill_names": list(skill_metadata_map.keys()),
        "install_results": install_results,
        "error": None if all_success else "部分或全部技能安装失败",
    }


async def _execute_install(skill_name: str, install_item: dict[str, Any]) -> dict[str, Any]:
    """执行单个安装方法"""
    kind = install_item.get("kind", "")
    label = install_item.get("label", f"安装 {skill_name}")

    logging.info(f"正在执行安装: {label} (kind={kind})")

    # 收集额外的搜索目录
    extra_dirs = await _get_extra_bin_dirs(kind)

    # 检查是否已安装
    bins = install_item.get("bins", [])
    if bins and await check_bins_exist(bins, extra_dirs=extra_dirs):
        return {"success": True, "output": f"已安装 (bins: {', '.join(bins)} 已存在)"}

    if kind == "brew":
        result = await _install_brew(install_item)
    elif kind == "go":
        result = await _install_go(install_item)
    elif kind == "uv":
        result = await _install_uv(install_item)
    elif kind == "choco":
        result = await _install_choco(install_item)
    elif kind == "apt":
        result = await _install_apt(install_item)
    elif kind == "node":
        result = await _install_node(install_item)
    elif kind == "pip":
        result = await _install_pip(install_item)
    else:
        return {"success": False, "error": f"不支持的安装类型: {kind}"}

    # 安装后二次验证
    if result.get("success") and bins:
        extra_dirs = await _get_extra_bin_dirs(kind)
        if not await check_bins_exist(bins, extra_dirs=extra_dirs):
            result["success"] = False
            result["error"] = (
                f"安装命令执行成功，但未找到二进制文件: {', '.join(bins)}。"
                f"请检查安装路径是否正确。"
            )

    return result


async def _get_extra_bin_dirs(kind: str) -> list[str]:
    """根据安装类型获取额外的 bin 搜索目录"""
    extra_dirs = []
    if kind == "go":
        gobin = await _get_go_bin_dir()
        if gobin:
            extra_dirs.append(gobin)
    return extra_dirs


# ============================================================
# 各类安装器
# ============================================================

async def _install_brew(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 Homebrew 安装"""
    formula = install_item.get("formula", "")
    if not formula:
        return {"success": False, "error": "缺少 formula 字段"}
    try:
        if "/" in formula:
            tap_name = "/".join(formula.split("/")[:2])
            await run(f"brew tap {tap_name}")
        return await _run_install_command(f"brew install {formula}")
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _install_go(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 go install 安装"""
    module = install_item.get("module", "")
    if not module:
        return {"success": False, "error": "缺少 module 字段"}

    try:
        result = await run(f"go install {module}")
        if not result.ok:
            return {"success": False, "output": result.stdout, "error": result.stderr}

        # go install 成功后，验证二进制文件是否真正可用
        bins = install_item.get("bins", [])
        if bins:
            gobin = await _get_go_bin_dir()
            if gobin:
                all_found = all((Path(gobin) / b).exists() for b in bins)
                if all_found:
                    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
                    if gobin not in path_dirs:
                        return {
                            "success": True,
                            "output": (
                                f"安装成功，二进制文件位于 {gobin}\n"
                                f"⚠️  注意：{gobin} 不在 PATH 中，请将以下内容添加到 shell 配置文件中：\n"
                                f'   export PATH="$PATH:{gobin}"'
                            ),
                            "error": None,
                        }

        return {"success": True, "output": result.stdout, "error": None}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _get_go_bin_dir() -> str | None:
    """获取 Go 的 bin 目录路径（GOBIN 或 GOPATH/bin）"""
    try:
        result = await run("go env GOBIN")
        if result.ok:
            gobin = result.stdout.strip()
            if gobin:
                return gobin

        result = await run("go env GOPATH")
        if result.ok:
            gopath = result.stdout.strip()
            if gopath:
                return str(Path(gopath) / "bin")
    except Exception:
        pass
    return None


async def _install_uv(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 uv pip install 安装"""
    return await _simple_install(install_item, "package", "uv pip install {pkg}")


async def _install_choco(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 Chocolatey 安装"""
    return await _simple_install(install_item, "package", "choco install {pkg} -y")


async def _install_apt(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 APT 安装"""
    package = install_item.get("package", "")
    if not package:
        return {"success": False, "error": "缺少 package 字段"}
    try:
        update_result = await run("sudo apt update")
        if not update_result.ok:
            return {
                "success": False,
                "output": update_result.stdout,
                "error": f"包列表更新失败: {update_result.stderr or '未知错误'}",
            }
        return await _run_install_command(f"sudo apt install {package} -y")
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _install_node(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 npm 或 yarn 安装 Node.js 包"""
    package = install_item.get("package", "")
    if not package:
        return {"success": False, "error": "缺少 package 字段"}

    package_manager = install_item.get("package_manager", "npm")
    is_global = install_item.get("global", False)

    try:
        if package_manager == "yarn":
            command = f"yarn global add {package}" if is_global else f"yarn add {package}"
        else:
            global_flag = "-g" if is_global else ""
            command = f"npm install {package} {global_flag}"
        return await _run_install_command(command)
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _install_pip(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 pip 安装 Python 包"""
    package = install_item.get("package", "")
    if not package:
        return {"success": False, "error": "缺少 package 字段"}
    try:
        user_flag = "--user" if install_item.get("global", False) else ""
        pip_command = install_item.get("pip_command", "pip")
        return await _run_install_command(f"{pip_command} install {package} {user_flag}")
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================
# 卸载
# ============================================================

async def uninstall_skills(skill_metadata_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """卸载指定的技能。

    参数：
        skill_metadata_map: {skill_name: front_matter} 字典

    返回结构：
    {
        "success": True/False,
        "skill_names": list[str],
        "uninstall_results": [{...}],
        "error": str | None
    }
    """
    if not skill_metadata_map:
        return {"success": False, "skill_names": [], "error": "未提供技能信息"}

    uninstall_results = []
    all_success = True

    for skill_name, metadata in skill_metadata_map.items():
        openclaw = metadata.get("metadata", {}).get("openclaw", {})
        install_list = openclaw.get("install", [])

        if not install_list:
            uninstall_results.append({
                "skill_name": skill_name,
                "success": False,
                "error": f"技能 '{skill_name}' 没有定义 openclaw.install 安装方法，无法确定如何卸载",
            })
            all_success = False
            continue

        current_platform = sys.platform
        filtered_install_list = _filter_install_list(install_list, current_platform)

        if not filtered_install_list:
            uninstall_results.append({
                "skill_name": skill_name,
                "success": False,
                "error": f"技能 '{skill_name}' 在当前操作系统 {current_platform} 下没有可用的卸载方法",
            })
            all_success = False
            continue

        uninstall_methods = []
        skill_success = True

        for install_item in filtered_install_list:
            install_id = install_item.get("id", "unknown")
            kind = install_item.get("kind", "")
            result = await _execute_uninstall(skill_name, install_item)
            uninstall_methods.append({
                "id": install_id,
                "kind": kind,
                "status": "success" if result["success"] else "failed",
                "output": result.get("output", ""),
                "error": result.get("error"),
            })
            if not result["success"]:
                skill_success = False

        uninstall_results.append({
            "skill_name": skill_name,
            "success": skill_success,
            "uninstall_methods": uninstall_methods,
            "error": None if skill_success else "部分或全部卸载方法执行失败",
        })
        if not skill_success:
            all_success = False

    return {
        "success": all_success,
        "skill_names": list(skill_metadata_map.keys()),
        "uninstall_results": uninstall_results,
        "error": None if all_success else "部分或全部技能卸载失败",
    }


async def _execute_uninstall(skill_name: str, install_item: dict[str, Any]) -> dict[str, Any]:
    """执行单个卸载方法"""
    kind = install_item.get("kind", "")
    label = install_item.get("label", f"卸载 {skill_name}")

    logging.info(f"正在执行卸载: {label} (kind={kind})")

    if kind == "brew":
        return await _uninstall_brew(install_item)
    elif kind == "go":
        return await _uninstall_go(install_item)
    elif kind == "uv":
        return await _uninstall_uv(install_item)
    elif kind == "choco":
        return await _uninstall_choco(install_item)
    elif kind == "apt":
        return await _uninstall_apt(install_item)
    elif kind == "node":
        return await _uninstall_node(install_item)
    elif kind == "pip":
        return await _uninstall_pip(install_item)
    else:
        return {"success": False, "error": f"不支持的卸载类型: {kind}"}


# ============================================================
# 各类卸载器
# ============================================================

async def _uninstall_brew(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 Homebrew 卸载"""
    return await _simple_uninstall(install_item, "formula", "brew uninstall {pkg}")


async def _uninstall_go(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过删除二进制文件卸载 Go 模块"""
    bins = install_item.get("bins", [])
    if bins:
        deleted = []
        for bin_name in bins:
            result = await run(f"which {bin_name}")
            if result.ok:
                bin_path = result.stdout.strip()
                if bin_path and Path(bin_path).exists():
                    Path(bin_path).unlink()
                    deleted.append(bin_path)
        if deleted:
            return {"success": True, "output": f"已删除: {', '.join(deleted)}"}
        return {"success": False, "error": f"未找到二进制文件: {bins}"}

    module = install_item.get("module", "")
    if not module:
        return {"success": False, "error": "缺少 module 和 bins 字段"}

    module_path = module.split("@")[0] if "@" in module else module

    try:
        result = await run(f"go list -f '{{{{.Target}}}}' {module_path}")
        if result.ok:
            install_path = result.stdout.strip()
            if install_path and Path(install_path).exists():
                Path(install_path).unlink()
                return {"success": True, "output": f"已删除 {install_path}"}
        return {"success": False, "error": "无法找到或删除 Go 模块"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _uninstall_uv(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 uv pip uninstall 卸载"""
    return await _simple_uninstall(install_item, "package", "uv pip uninstall {pkg} -y")


async def _uninstall_choco(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 Chocolatey 卸载"""
    return await _simple_uninstall(install_item, "package", "choco uninstall {pkg} -y")


async def _uninstall_apt(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 APT 卸载"""
    return await _run_pkg_command(install_item, "package", "sudo apt remove {pkg} -y")


async def _uninstall_node(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 npm 或 yarn 卸载 Node.js 包"""
    package = install_item.get("package", "")
    if not package:
        return {"success": False, "error": "缺少 package 字段"}

    package_manager = install_item.get("package_manager", "npm")
    is_global = install_item.get("global", False)

    try:
        if package_manager == "yarn":
            command = f"yarn global remove {package}" if is_global else f"yarn remove {package}"
        else:
            global_flag = "-g" if is_global else ""
            command = f"npm uninstall {package} {global_flag}"
        return await _run_install_command(command)
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _uninstall_pip(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 pip 卸载 Python 包"""
    package = install_item.get("package", "")
    if not package:
        return {"success": False, "error": "缺少 package 字段"}
    try:
        user_flag = "--user" if install_item.get("global", False) else ""
        pip_command = install_item.get("pip_command", "pip")
        return await _run_install_command(f"{pip_command} uninstall {package} {user_flag} -y")
    except Exception as e:
        return {"success": False, "error": str(e)}
