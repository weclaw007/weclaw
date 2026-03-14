#!/usr/bin/env python3
"""
Claw 命令行入口

功能：
- install 命令：执行安装流程
- doctor 命令：检查安装环境是否就绪

用法：
  claw install    # 执行安装流程
  claw doctor     # 检查安装环境
"""

import argparse
import sys


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="Claw 命令行工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # install 子命令
    subparsers.add_parser("install", help="执行安装流程")

    # doctor 子命令
    subparsers.add_parser("doctor", help="检查安装环境")

    args = parser.parse_args()

    if args.command == "install":
        from weclaw.cli.install import install_main
        import asyncio
        return asyncio.run(install_main())
    elif args.command == "doctor":
        from weclaw.cli.doctor import main as doctor_main
        return doctor_main()
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
