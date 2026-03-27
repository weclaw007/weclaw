"""IM Bot 适配器模块 - v2 Adapter 模式。

将 v1 的 3 个独立进程（WebSocket Server + 飞书 Bot + Telegram Bot）
合并为 1 个进程，每个 Bot 以 Adapter 形式直接调用 Agent。
"""

from weclaw.adapters.base import BaseAdapter

__all__ = ["BaseAdapter"]
