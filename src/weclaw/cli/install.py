#!/usr/bin/env python3
import asyncio
import sys
import time
from pathlib import Path

"""
Claw 安装脚本

功能：
- 检查安装环境并自动安装缺失的依赖

用法：
  claw install     # 通过 claw 命令行执行安装
"""

import platform

from weclaw.agent.skill_manager import SkillManager
from weclaw.agent.skill_operations import install_skills, check_skills_installed
from weclaw.utils.console import (
    BOLD, RESET,
    print_section, print_success, print_fail,
    print_info, print_warn, format_duration,
)
from weclaw.utils.paths import get_third_party_skills_dir


def is_windows():
    """检查当前操作系统是否为Windows"""
    return platform.system().lower() == 'windows'


async def install_main():
    """安装流程主函数：加载技能列表并逐个安装，打印详细日志"""
    total_start = time.time()

    print_section("Claw 技能安装")
    print_info(f"当前操作系统: {sys.platform}")

    # ---- 第1步：加载所有技能（内置 + 第三方） ----
    print(f"\n{BOLD}[1/3] 加载技能列表...{RESET}")
    builtin_skills_dir = Path(__file__).resolve().parent.parent / "skills"
    third_party_skills_dir = get_third_party_skills_dir()
    print_info(f"内置技能目录: {builtin_skills_dir}")
    print_info(f"第三方技能目录: {third_party_skills_dir}")

    skill_manager = SkillManager.get_instance(builtin_skills_dir)
    all_skills = await skill_manager.load()

    if not all_skills:
        print_warn("未找到任何技能，请检查 skills 目录")
        return 1

    # 统计内置和第三方技能数量
    third_party_ids = set()
    if third_party_skills_dir.exists():
        third_party_ids = {p.parent.name for p in third_party_skills_dir.glob("*/SKILL.md")}
    builtin_count = len([s for s in all_skills if s not in third_party_ids])
    third_party_count = len([s for s in all_skills if s in third_party_ids])

    print_info(f"共发现 {len(all_skills)} 个技能（内置 {builtin_count} 个，第三方 {third_party_count} 个）")

    # ---- 第2步：过滤当前系统可用的技能 ----
    print(f"\n{BOLD}[2/3] 过滤当前系统可用技能...{RESET}")
    compatible_skills = skill_manager.get_skills_for_current_os()

    if not compatible_skills:
        print_warn("当前操作系统下没有可用的技能")
        return 1

    print_info(f"当前系统可用技能 {len(compatible_skills)} 个：")
    for idx, (skill_id, meta) in enumerate(compatible_skills.items(), 1):
        name = meta.get("name", skill_id)
        desc = meta.get("description", "无描述")
        print(f"    {idx}. {BOLD}{name}{RESET} ({skill_id}) - {desc}")

    # ---- 第3步：逐个安装技能 ----
    print(f"\n{BOLD}[3/3] 开始安装技能...{RESET}")

    skill_ids = list(compatible_skills.keys())
    success_count = 0
    fail_count = 0
    skip_count = 0

    for idx, skill_id in enumerate(skill_ids, 1):
        meta = compatible_skills[skill_id]
        skill_name = meta.get("name", skill_id)

        print(f"\n  {BOLD}[{idx}/{len(skill_ids)}] 安装 {skill_name} ({skill_id}){RESET}")
        print(f"  {'─' * 50}")

        # 检查是否已安装
        print_info("检查安装状态...")
        already_installed = await check_skills_installed(meta)

        if already_installed:
            print_success("已安装，跳过")
            skip_count += 1
            continue

        # 执行安装
        print_info("开始安装...")
        skill_start = time.time()

        result = await install_skills({skill_id: meta})

        skill_duration = time.time() - skill_start

        # 解析安装结果
        if result.get("install_results"):
            skill_result = result["install_results"][0]

            # 打印每个安装方法的详细信息
            for method in skill_result.get("install_methods", []):
                method_id = method.get("id", "unknown")
                kind = method.get("kind", "unknown")
                status = method.get("status", "unknown")
                output = method.get("output", "").strip()
                error = method.get("error")

                if status == "success":
                    print_success(f"[{kind}] {method_id} - 安装成功")
                else:
                    print_fail(f"[{kind}] {method_id} - 安装失败")

                # 打印输出详情（截取前5行避免过长）
                detail_text = output or (error if error else "")
                if detail_text:
                    detail_lines = detail_text.splitlines()
                    for line in detail_lines[:5]:
                        print(f"       {line}")
                    if len(detail_lines) > 5:
                        print(f"       ... (共 {len(detail_lines)} 行，已省略)")

            if skill_result.get("success"):
                print_success(f"安装完成 (耗时 {format_duration(skill_duration)})")
                success_count += 1
            else:
                error_msg = skill_result.get("error", "未知错误")
                print_fail(f"安装失败: {error_msg} (耗时 {format_duration(skill_duration)})")
                fail_count += 1
        else:
            error_msg = result.get("error", "未知错误")
            print_fail(f"安装失败: {error_msg}")
            fail_count += 1

    # ---- 安装汇总 ----
    total_duration = time.time() - total_start
    print_section("安装完成汇总")
    print_info(f"总计技能: {len(skill_ids)} 个")
    if success_count > 0:
        print_success(f"安装成功: {success_count} 个")
    if skip_count > 0:
        print_info(f"已安装跳过: {skip_count} 个")
    if fail_count > 0:
        print_fail(f"安装失败: {fail_count} 个")
    print_info(f"总耗时: {format_duration(total_duration)}")
    print()

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    # 启动asyncio事件循环，统一调度所有异步任务
    asyncio.run(install_main())
