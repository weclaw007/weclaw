"""技能管理 - 安装/卸载/状态检查模块"""

import logging
import os
import sys
from pathlib import Path
from typing import Any

from weclaw.utils.command import run_command, check_bins_exist


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


async def check_skills_installed(skill_metadata: dict[str, Any]) -> bool:
    """
    检查指定的技能是否已安装。

    参数：
        skill_metadata: 技能的 front_matter 元数据对象

    只判断 openclaw.requires.bins 中要求的二进制文件是否存在于 PATH 中（或安装类型对应的额外目录中）。
    如果没有定义 requires.bins，则视为已安装（无外部依赖）。

    返回：True（已安装）或 False（未安装）
    """
    if not skill_metadata:
        return False

    openclaw = skill_metadata.get("metadata", {}).get("openclaw", {})
    requires = openclaw.get("requires", {})
    bins = requires.get("bins", [])

    # 如果没有定义 requires.bins，视为无外部依赖，直接返回已安装
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
    """
    安装指定的技能。

    参数：
        skill_metadata_map: {skill_name: front_matter} 字典，包含需要安装的技能及其元数据

    返回结构：
    {
        "success": True/False,
        "skill_names": list[str],
        "install_results": [{...}],
        "error": str | None
    }
    """
    if not skill_metadata_map:
        return {
            "success": False,
            "skill_names": [],
            "error": "未提供技能信息"
        }

    install_results = []
    all_success = True

    for skill_name, metadata in skill_metadata_map.items():
        # 检查操作系统兼容性
        openclaw = metadata.get("metadata", {}).get("openclaw", {})
        required_os = openclaw.get("os", [])

        if required_os and sys.platform not in required_os:
            result = {
                "skill_name": skill_name,
                "success": False,
                "error": f"技能 '{skill_name}' 要求操作系统 {required_os}，但当前系统为 {sys.platform}"
            }
            install_results.append(result)
            all_success = False
            continue

        install_list = openclaw.get("install", [])

        if not install_list:
            result = {
                "skill_name": skill_name,
                "success": False,
                "error": f"技能 '{skill_name}' 没有定义 openclaw.install 安装方法"
            }
            install_results.append(result)
            all_success = False
            continue

        current_platform = sys.platform
        filtered_install_list = _filter_install_list(install_list, current_platform)

        if not filtered_install_list:
            result = {
                "skill_name": skill_name,
                "success": False,
                "error": f"技能 '{skill_name}' 在当前操作系统 {current_platform} 下没有可用的安装方法"
            }
            install_results.append(result)
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
                "error": result.get("error")
            })

            if not result["success"]:
                skill_success = False

        result = {
            "skill_name": skill_name,
            "success": skill_success,
            "install_methods": install_methods,
            "error": None if skill_success else "部分或全部安装方法执行失败"
        }
        install_results.append(result)

        if not skill_success:
            all_success = False

    return {
        "success": all_success,
        "skill_names": list(skill_metadata_map.keys()),
        "install_results": install_results,
        "error": None if all_success else "部分或全部技能安装失败"
    }


async def _execute_install(skill_name: str, install_item: dict[str, Any]) -> dict[str, Any]:
    """执行单个安装方法"""
    kind = install_item.get("kind", "")
    label = install_item.get("label", f"安装 {skill_name}")

    logging.info(f"正在执行安装: {label} (kind={kind})")

    # 收集额外的搜索目录（用于某些安装方式二进制不在 PATH 中的情况）
    extra_dirs = await _get_extra_bin_dirs(kind)

    # 检查是否已安装
    bins = install_item.get("bins", [])
    if bins and await check_bins_exist(bins, extra_dirs=extra_dirs):
        return {
            "success": True,
            "output": f"已安装 (bins: {', '.join(bins)} 已存在)"
        }

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
        return {
            "success": False,
            "error": f"不支持的安装类型: {kind}"
        }

    # 安装后二次验证：确认二进制文件是否真正可用
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


async def _install_brew(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 Homebrew 安装"""
    formula = install_item.get("formula", "")
    if not formula:
        return {"success": False, "error": "缺少 formula 字段"}

    try:
        if "/" in formula:
            tap_name = "/".join(formula.split("/")[:2])
            await run_command(f"brew tap {tap_name}")

        result = await run_command(f"brew install {formula}")
        return {
            "success": result["returncode"] == 0,
            "output": result.get("stdout", ""),
            "error": result.get("stderr") if result["returncode"] != 0 else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _install_go(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 go install 安装"""
    module = install_item.get("module", "")
    if not module:
        return {"success": False, "error": "缺少 module 字段"}

    try:
        result = await run_command(f"go install {module}")
        if result["returncode"] != 0:
            return {
                "success": False,
                "output": result.get("stdout", ""),
                "error": result.get("stderr")
            }

        # go install 成功后，验证二进制文件是否真正可用
        bins = install_item.get("bins", [])
        if bins:
            # 获取 GOBIN 或 GOPATH/bin 路径
            gobin = await _get_go_bin_dir()
            if gobin:
                # 检查二进制文件是否存在于 go bin 目录
                all_found = True
                for bin_name in bins:
                    bin_path = Path(gobin) / bin_name
                    if not bin_path.exists():
                        all_found = False
                        break

                if all_found:
                    # 检查 go bin 目录是否在 PATH 中
                    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
                    if gobin not in path_dirs:
                        return {
                            "success": True,
                            "output": f"安装成功，二进制文件位于 {gobin}\n"
                                     f"⚠️  注意：{gobin} 不在 PATH 中，请将以下内容添加到 shell 配置文件中：\n"
                                     f"   export PATH=\"$PATH:{gobin}\"",
                            "error": None
                        }

        return {
            "success": True,
            "output": result.get("stdout", ""),
            "error": None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _get_go_bin_dir() -> str | None:
    """获取 Go 的 bin 目录路径（GOBIN 或 GOPATH/bin）"""
    try:
        # 优先使用 GOBIN
        result = await run_command("go env GOBIN", capture=True)
        if result["returncode"] == 0:
            gobin = result.get("stdout", "").strip()
            if gobin:
                return gobin

        # 回退到 GOPATH/bin
        result = await run_command("go env GOPATH", capture=True)
        if result["returncode"] == 0:
            gopath = result.get("stdout", "").strip()
            if gopath:
                return str(Path(gopath) / "bin")
    except Exception:
        pass
    return None


async def _install_uv(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 uv pip install 安装"""
    package = install_item.get("package", "")
    if not package:
        return {"success": False, "error": "缺少 package 字段"}

    try:
        result = await run_command(f"uv pip install {package}")
        return {
            "success": result["returncode"] == 0,
            "output": result.get("stdout", ""),
            "error": result.get("stderr") if result["returncode"] != 0 else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _install_choco(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 Chocolatey 安装"""
    package = install_item.get("package", "")
    if not package:
        return {"success": False, "error": "缺少 package 字段"}

    try:
        result = await run_command(f"choco install {package} -y")
        return {
            "success": result["returncode"] == 0,
            "output": result.get("stdout", ""),
            "error": result.get("stderr") if result["returncode"] != 0 else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _install_apt(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 APT (Advanced Package Tool) 安装"""
    package = install_item.get("package", "")
    if not package:
        return {"success": False, "error": "缺少 package 字段"}

    try:
        update_result = await run_command("sudo apt update")
        if update_result["returncode"] != 0:
            return {
                "success": False,
                "output": update_result.get("stdout", ""),
                "error": f"包列表更新失败: {update_result.get('stderr', '未知错误')}"
            }

        result = await run_command(f"sudo apt install {package} -y")
        return {
            "success": result["returncode"] == 0,
            "output": result.get("stdout", ""),
            "error": result.get("stderr") if result["returncode"] != 0 else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _install_node(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 npm 或 yarn 安装 Node.js 包"""
    package = install_item.get("package", "")
    if not package:
        return {"success": False, "error": "缺少 package 字段"}

    package_manager = install_item.get("package_manager", "npm")

    try:
        is_global = install_item.get("global", False)
        global_flag = "-g" if is_global else ""

        if package_manager == "yarn":
            command = f"yarn global add {package}" if is_global else f"yarn add {package}"
        else:
            command = f"npm install {package} {global_flag}"

        result = await run_command(command)
        return {
            "success": result["returncode"] == 0,
            "output": result.get("stdout", ""),
            "error": result.get("stderr") if result["returncode"] != 0 else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _install_pip(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 pip 安装 Python 包"""
    package = install_item.get("package", "")
    if not package:
        return {"success": False, "error": "缺少 package 字段"}

    try:
        is_global = install_item.get("global", False)
        user_flag = "--user" if is_global else ""
        pip_command = install_item.get("pip_command", "pip")

        command = f"{pip_command} install {package} {user_flag}"
        result = await run_command(command)
        return {
            "success": result["returncode"] == 0,
            "output": result.get("stdout", ""),
            "error": result.get("stderr") if result["returncode"] != 0 else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================
# 卸载
# ============================================================

async def uninstall_skills(skill_metadata_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """
    卸载指定的技能，根据技能的安装类型执行相应的卸载命令。

    参数：
        skill_metadata_map: {skill_name: front_matter} 字典，包含需要卸载的技能及其元数据

    返回结构：
    {
        "success": True/False,
        "skill_names": list[str],
        "uninstall_results": [{...}],
        "error": str | None
    }
    """
    if not skill_metadata_map:
        return {
            "success": False,
            "skill_names": [],
            "error": "未提供技能信息"
        }

    uninstall_results = []
    all_success = True

    for skill_name, metadata in skill_metadata_map.items():
        # 获取技能的安装配置
        openclaw = metadata.get("metadata", {}).get("openclaw", {})
        install_list = openclaw.get("install", [])

        if not install_list:
            result = {
                "skill_name": skill_name,
                "success": False,
                "error": f"技能 '{skill_name}' 没有定义 openclaw.install 安装方法，无法确定如何卸载"
            }
            uninstall_results.append(result)
            all_success = False
            continue

        current_platform = sys.platform
        filtered_install_list = _filter_install_list(install_list, current_platform)

        if not filtered_install_list:
            result = {
                "skill_name": skill_name,
                "success": False,
                "error": f"技能 '{skill_name}' 在当前操作系统 {current_platform} 下没有可用的卸载方法"
            }
            uninstall_results.append(result)
            all_success = False
            continue

        # 执行过滤后的卸载方法
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
                "error": result.get("error")
            })

            if not result["success"]:
                skill_success = False

        result = {
            "skill_name": skill_name,
            "success": skill_success,
            "uninstall_methods": uninstall_methods,
            "error": None if skill_success else "部分或全部卸载方法执行失败"
        }
        uninstall_results.append(result)

        if not skill_success:
            all_success = False

    return {
        "success": all_success,
        "skill_names": list(skill_metadata_map.keys()),
        "uninstall_results": uninstall_results,
        "error": None if all_success else "部分或全部技能卸载失败"
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
        return {
            "success": False,
            "error": f"不支持的卸载类型: {kind}"
        }


async def _uninstall_brew(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 Homebrew 卸载"""
    formula = install_item.get("formula", "")
    if not formula:
        return {"success": False, "error": "缺少 formula 字段"}

    try:
        result = await run_command(f"brew uninstall {formula}")
        return {
            "success": result["returncode"] == 0,
            "output": result.get("stdout", ""),
            "error": result.get("stderr") if result["returncode"] != 0 else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _uninstall_go(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过删除二进制文件卸载 Go 模块"""
    import shutil

    # 优先通过 bins 字段查找并删除二进制文件
    bins = install_item.get("bins", [])
    if bins:
        deleted = []
        for bin_name in bins:
            result = await run_command(f"which {bin_name}")
            if result["returncode"] == 0:
                bin_path = result.get("stdout", "").strip()
                if bin_path and Path(bin_path).exists():
                    Path(bin_path).unlink()
                    deleted.append(bin_path)
        if deleted:
            return {"success": True, "output": f"已删除: {', '.join(deleted)}"}
        return {"success": False, "error": f"未找到二进制文件: {bins}"}

    # 回退到 go list 查找（去除 @version 后缀）
    module = install_item.get("module", "")
    if not module:
        return {"success": False, "error": "缺少 module 和 bins 字段"}

    module_path = module.split("@")[0] if "@" in module else module

    try:
        result = await run_command(f"go list -f '{{{{.Target}}}}' {module_path}")
        if result["returncode"] == 0:
            install_path = result.get("stdout", "").strip()
            if install_path and Path(install_path).exists():
                Path(install_path).unlink()
                return {"success": True, "output": f"已删除 {install_path}"}

        return {"success": False, "error": "无法找到或删除 Go 模块"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _uninstall_uv(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 uv pip uninstall 卸载"""
    package = install_item.get("package", "")
    if not package:
        return {"success": False, "error": "缺少 package 字段"}

    try:
        result = await run_command(f"uv pip uninstall {package} -y")
        return {
            "success": result["returncode"] == 0,
            "output": result.get("stdout", ""),
            "error": result.get("stderr") if result["returncode"] != 0 else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _uninstall_choco(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 Chocolatey 卸载"""
    package = install_item.get("package", "")
    if not package:
        return {"success": False, "error": "缺少 package 字段"}

    try:
        result = await run_command(f"choco uninstall {package} -y")
        return {
            "success": result["returncode"] == 0,
            "output": result.get("stdout", ""),
            "error": result.get("stderr") if result["returncode"] != 0 else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _uninstall_apt(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 APT 卸载"""
    package = install_item.get("package", "")
    if not package:
        return {"success": False, "error": "缺少 package 字段"}

    try:
        result = await run_command(f"sudo apt remove {package} -y")
        return {
            "success": result["returncode"] == 0,
            "output": result.get("stdout", ""),
            "error": result.get("stderr") if result["returncode"] != 0 else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _uninstall_node(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 npm 或 yarn 卸载 Node.js 包"""
    package = install_item.get("package", "")
    if not package:
        return {"success": False, "error": "缺少 package 字段"}

    package_manager = install_item.get("package_manager", "npm")

    try:
        is_global = install_item.get("global", False)
        global_flag = "-g" if is_global else ""

        if package_manager == "yarn":
            command = f"yarn global remove {package}" if is_global else f"yarn remove {package}"
        else:
            command = f"npm uninstall {package} {global_flag}"

        result = await run_command(command)
        return {
            "success": result["returncode"] == 0,
            "output": result.get("stdout", ""),
            "error": result.get("stderr") if result["returncode"] != 0 else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _uninstall_pip(install_item: dict[str, Any]) -> dict[str, Any]:
    """通过 pip 卸载 Python 包"""
    package = install_item.get("package", "")
    if not package:
        return {"success": False, "error": "缺少 package 字段"}

    try:
        is_global = install_item.get("global", False)
        user_flag = "--user" if is_global else ""
        pip_command = install_item.get("pip_command", "pip")

        command = f"{pip_command} uninstall {package} {user_flag} -y"
        result = await run_command(command)
        return {
            "success": result["returncode"] == 0,
            "output": result.get("stdout", ""),
            "error": result.get("stderr") if result["returncode"] != 0 else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
