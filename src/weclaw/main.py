"""Weclaw v2 统一入口 — 一个进程运行所有服务。

根据环境变量按需启动：
- WebSocket 服务器（始终启动）
- 飞书适配器（LARK_APP_ID + LARK_APP_SECRET 存在时启动）
- Telegram 适配器（TELEGRAM_BOT_TOKEN 存在时启动）
"""

import asyncio
import logging
import os
import signal
from pathlib import Path

from dotenv import load_dotenv, find_dotenv

from weclaw.gateway.server import Server
from weclaw.skill_mgr.manager import SkillManager

logger = logging.getLogger(__name__)


async def main() -> None:
    """主函数：初始化 SkillManager → 启动 WebSocket + 适配器。"""

    # 1. 初始化全局 SkillManager
    skills_dir = Path(__file__).resolve().parent / "skills"
    skill_manager = SkillManager.get_instance(skills_dir)
    await skill_manager.load()
    skill_manager.rebuild_active_skills_dir()
    logger.info(f"SkillManager 已加载，技能目录: {skills_dir}")

    # 2. 收集要运行的异步任务
    tasks: list[asyncio.Task] = []
    adapters = []

    # 2a. WebSocket 服务器（始终启动）
    ws_host = os.environ.get("WS_HOST", "0.0.0.0")
    ws_port = int(os.environ.get("WS_PORT", "4567"))
    server = Server(host=ws_host, port=ws_port)
    tasks.append(asyncio.create_task(server.start(), name="websocket-server"))
    logger.info(f"WebSocket 服务器任务已创建: ws://{ws_host}:{ws_port}")

    # 2b. 飞书适配器（按需启动）
    lark_app_id = os.environ.get("LARK_APP_ID")
    lark_app_secret = os.environ.get("LARK_APP_SECRET")
    if lark_app_id and lark_app_secret:
        from weclaw.adapters.feishu_adapter import FeishuAdapter
        feishu = FeishuAdapter(app_id=lark_app_id, app_secret=lark_app_secret)
        adapters.append(feishu)
        tasks.append(asyncio.create_task(feishu.start(), name="feishu-adapter"))
        logger.info("飞书适配器任务已创建")
    else:
        logger.info("飞书适配器未启用（缺少 LARK_APP_ID / LARK_APP_SECRET）")

    # 2c. Telegram 适配器（按需启动）
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if telegram_token:
        from weclaw.adapters.telegram_adapter import TelegramAdapter
        telegram = TelegramAdapter(token=telegram_token)
        adapters.append(telegram)
        tasks.append(asyncio.create_task(telegram.start(), name="telegram-adapter"))
        logger.info("Telegram 适配器任务已创建")
    else:
        logger.info("Telegram 适配器未启用（缺少 TELEGRAM_BOT_TOKEN）")

    # 3. 注册优雅关闭
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("收到停止信号，正在关闭...")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows 不支持 add_signal_handler
            pass

    # 4. 等待：任意任务结束 或 收到关闭信号
    if tasks:
        shutdown_task = asyncio.create_task(shutdown_event.wait(), name="shutdown-wait")
        done, pending = await asyncio.wait(
            [*tasks, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # 检查是否有任务异常退出
        for t in done:
            if t.get_name() != "shutdown-wait" and not t.cancelled() and t.exception():
                logger.error(f"任务 [{t.get_name()}] 异常退出: {t.exception()}")

    # 5. 清理：停止所有适配器
    for adapter in adapters:
        try:
            await adapter.stop()
        except Exception as e:
            name = getattr(adapter, "adapter_name", type(adapter).__name__)
            logger.warning(f"关闭适配器 [{name}] 时出错: {e}")

    # 取消所有未完成的任务
    for t in tasks:
        if not t.done():
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    logger.info("所有服务已停止")


def run() -> None:
    """CLI 入口点。"""
    load_dotenv(find_dotenv(usecwd=True))
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    )
    print("=" * 60)
    print("  Weclaw v2 — Unified Agent Server")
    print("=" * 60)
    asyncio.run(main())


if __name__ == "__main__":
    run()
