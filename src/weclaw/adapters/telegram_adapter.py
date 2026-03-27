"""Telegram 适配器 - 将 Telegram 消息转发到 Agent 并将回复发回 Telegram。

v1 → v2 改造要点：
- 去掉 WebSocket 客户端连接（不再是独立进程）
- 直接在进程内调用 Agent.astream_text() 获取回复
- Telegram 原生 async，无需 asyncio.to_thread
- 保留 Markdown → Telegram HTML 转换
"""

import asyncio
import logging
import os
import re
from pathlib import Path

import unicodedata
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from weclaw.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)


# ── Markdown → Telegram HTML 转换（与 v1 一致）──────────────────


def _strip_md(s: str) -> str:
    """Strip markdown inline formatting from text."""
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
    s = re.sub(r'__(.+?)__', r'\1', s)
    s = re.sub(r'~~(.+?)~~', r'\1', s)
    s = re.sub(r'`([^`]+)`', r'\1', s)
    return s.strip()


def _render_table_box(table_lines: list[str]) -> str:
    """Convert markdown pipe-table to compact aligned text for <pre> display."""

    def dw(s: str) -> int:
        return sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in s)

    rows: list[list[str]] = []
    has_sep = False
    for line in table_lines:
        cells = [_strip_md(c) for c in line.strip().strip('|').split('|')]
        if all(re.match(r'^:?-+:?$', c) for c in cells if c):
            has_sep = True
            continue
        rows.append(cells)
    if not rows or not has_sep:
        return '\n'.join(table_lines)

    ncols = max(len(r) for r in rows)
    for r in rows:
        r.extend([''] * (ncols - len(r)))
    widths = [max(dw(r[c]) for r in rows) for c in range(ncols)]

    def dr(cells: list[str]) -> str:
        return '  '.join(f'{c}{" " * (w - dw(c))}' for c, w in zip(cells, widths))

    out = [dr(rows[0])]
    out.append('  '.join('─' * w for w in widths))
    for row in rows[1:]:
        out.append(dr(row))
    return '\n'.join(out)


def _markdown_to_telegram_html(text: str) -> str:
    """Convert markdown to Telegram-safe HTML."""
    if not text:
        return ""

    # 1. Extract and protect code blocks
    code_blocks: list[str] = []

    def save_code_block(m: re.Match) -> str:
        code_blocks.append(m.group(1))
        return f"\x00CB{len(code_blocks) - 1}\x00"

    text = re.sub(r'```[\w]*\n?([\s\S]*?)```', save_code_block, text)

    # 1.5. Convert markdown tables to box-drawing
    lines = text.split('\n')
    rebuilt: list[str] = []
    li = 0
    while li < len(lines):
        if re.match(r'^\s*\|.+\|', lines[li]):
            tbl: list[str] = []
            while li < len(lines) and re.match(r'^\s*\|.+\|', lines[li]):
                tbl.append(lines[li])
                li += 1
            box = _render_table_box(tbl)
            if box != '\n'.join(tbl):
                code_blocks.append(box)
                rebuilt.append(f"\x00CB{len(code_blocks) - 1}\x00")
            else:
                rebuilt.extend(tbl)
        else:
            rebuilt.append(lines[li])
            li += 1
    text = '\n'.join(rebuilt)

    # 2. Extract and protect inline code
    inline_codes: list[str] = []

    def save_inline_code(m: re.Match) -> str:
        inline_codes.append(m.group(1))
        return f"\x00IC{len(inline_codes) - 1}\x00"

    text = re.sub(r'`([^`]+)`', save_inline_code, text)

    # 3. Headers
    text = re.sub(r'^#{1,6}\s+(.+)$', r'\1', text, flags=re.MULTILINE)

    # 4. Blockquotes
    text = re.sub(r'^>\s*(.*)$', r'\1', text, flags=re.MULTILINE)

    # 5. Escape HTML
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 6. Links
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

    # 7. Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)

    # 8. Italic
    text = re.sub(r'(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])', r'<i>\1</i>', text)

    # 9. Strikethrough
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)

    # 10. Bullet lists
    text = re.sub(r'^[-*]\s+', '• ', text, flags=re.MULTILINE)

    # 11. Restore inline code
    for i, code in enumerate(inline_codes):
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00IC{i}\x00", f"<code>{escaped}</code>")

    # 12. Restore code blocks
    for i, code in enumerate(code_blocks):
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00CB{i}\x00", f"<pre><code>{escaped}</code></pre>")

    return text


# ── Telegram 适配器 ──────────────────────────────────────────


class TelegramAdapter(BaseAdapter):
    """Telegram Bot 适配器 - 通过 polling 接收消息，直接调用 Agent 处理。"""

    def __init__(self, token: str) -> None:
        self._token = token
        self.application: Application | None = None
        self._shutdown_event = asyncio.Event()
        self._stop_called = False
        # 先初始化自身属性，再调用 super().__init__（因为 transport 需要 self 引用）
        super().__init__(
            adapter_name="telegram",
            message_transport=TelegramMessageTransport(self),
        )

    @property
    def token(self) -> str:
        return self._token

    @property
    def default_chat_id(self) -> str:
        """message 工具交互的默认聊天 ID"""
        return os.getenv("TELEGRAM_CHAT_ID", "")

    # ── 命令处理 ──────────────────────────────────────────────

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /start 命令"""
        user = update.effective_user
        if self._stopped:
            self._stopped = False
            logger.info(f"用户 {user.first_name} ({user.id}) 重新启动了机器人")
            await update.message.reply_text(
                f"欢迎回来 {user.first_name}！\n\n"
                "机器人已重新启动，可以继续发送消息了。"
            )
            return
        await update.message.reply_text(
            f"你好 {user.first_name}！\n\n"
            "我是一个智能助手机器人。\n"
            "发送任意消息给我，我会帮你处理。\n"
        )

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /help 命令"""
        await update.message.reply_text(
            "帮助信息：\n\n"
            "/start - 启动机器人\n"
            "/help - 查看此帮助信息\n"
            "/stop - 停止机器人\n\n"
            "直接发送文本消息，我会使用 AI 助手回复你。"
        )

    async def _cmd_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /stop 命令"""
        logger.info(f"收到停止命令，来自用户: {update.effective_user.id}")
        self._stopped = True
        await update.message.reply_text(
            "机器人已停止接收消息。\n"
            "发送 /start 可重新启动。"
        )

    # ── 消息处理（v2：直接调用 Agent）──────────────────────────

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理普通文本消息"""
        if self._stopped:
            await update.message.reply_text("机器人已停止，发送 /start 重新启动。")
            return

        user_message = update.message.text
        user = update.effective_user
        logger.info(f"收到消息来自 {user.first_name} ({user.id}): {user_message}")

        try:
            reply = await self.ask_agent(user_message)
            if reply:
                html_reply = _markdown_to_telegram_html(reply)
                await self.application.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=html_reply,
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text("(无响应内容)")
        except Exception as e:
            logger.exception(f"处理消息失败: {e}")
            await update.message.reply_text(f"处理失败: {str(e)}")

    async def _handle_location(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理位置消息"""
        if self._stopped:
            await update.message.reply_text(self._STOPPED_REPLY)
            return

        location = update.message.location
        user = update.effective_user
        logger.info(f"收到位置消息来自 {user.first_name} ({user.id}): ({location.latitude}, {location.longitude})")

        try:
            prompt = f"用户发送了位置: 纬度 {location.latitude}, 经度 {location.longitude}"
            reply = await self.ask_agent(prompt)
            if reply:
                html_reply = _markdown_to_telegram_html(reply)
                await self.application.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=html_reply,
                    parse_mode="HTML",
                )
        except Exception as e:
            logger.exception(f"处理位置消息失败: {e}")
            await update.message.reply_text(f"处理失败: {str(e)}")

    async def _error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理错误"""
        logger.error(f"更新 {update} 导致错误 {context.error}")

    # ── 生命周期管理 ──────────────────────────────────────────

    def _setup_handlers(self) -> None:
        """注册所有命令和消息处理器"""
        if not self.application:
            raise RuntimeError("Application 未初始化")

        self.application.add_handler(CommandHandler("start", self._cmd_start))
        self.application.add_handler(CommandHandler("help", self._cmd_help))
        self.application.add_handler(CommandHandler("stop", self._cmd_stop))
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )
        self.application.add_handler(
            MessageHandler(filters.LOCATION, self._handle_location)
        )
        self.application.add_error_handler(self._error_handler)

    async def start(self) -> None:
        """启动 Telegram 适配器"""
        # 读取 Telegram 技能 SKILL.md 作为 inject prompt
        inject_prompt = ""
        skill_md_path = Path(__file__).resolve().parent.parent / "skills" / "telegram" / "SKILL.md"
        if skill_md_path.exists():
            inject_prompt = skill_md_path.read_text(encoding="utf-8")

        await self.initialize_agent(inject_prompt=inject_prompt)

        # 创建 Application
        self.application = Application.builder().token(self.token).build()
        self._setup_handlers()

        logger.info("Telegram 适配器启动中...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling(allowed_updates=Update.ALL_TYPES)

        logger.info("Telegram 适配器运行中...")

        # 保持运行
        try:
            await self._shutdown_event.wait()
        finally:
            await self.stop()

    async def stop(self) -> None:
        """停止 Telegram 适配器"""
        logger.info("Telegram 适配器停止中...")
        self._shutdown_event.set()

        if self.application:
            if self.application.updater:
                await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
            logger.info("Telegram bot 已停止")

        await self.close()
        logger.info("Telegram 适配器已停止")
