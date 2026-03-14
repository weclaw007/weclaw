import asyncio
import json
import logging
import os
import re
import uuid
import websockets
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import unicodedata

# 配置日志
logging.basicConfig(
    format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)



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
    """
    Convert markdown to Telegram-safe HTML.
    """
    if not text:
        return ""

    # 1. Extract and protect code blocks (preserve content from other processing)
    code_blocks: list[str] = []
    def save_code_block(m: re.Match) -> str:
        code_blocks.append(m.group(1))
        return f"\x00CB{len(code_blocks) - 1}\x00"

    text = re.sub(r'```[\w]*\n?([\s\S]*?)```', save_code_block, text)

    # 1.5. Convert markdown tables to box-drawing (reuse code_block placeholders)
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

    # 3. Headers # Title -> just the title text
    text = re.sub(r'^#{1,6}\s+(.+)$', r'\1', text, flags=re.MULTILINE)

    # 4. Blockquotes > text -> just the text (before HTML escaping)
    text = re.sub(r'^>\s*(.*)$', r'\1', text, flags=re.MULTILINE)

    # 5. Escape HTML special characters
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 6. Links [text](url) - must be before bold/italic to handle nested cases
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

    # 7. Bold **text** or __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)

    # 8. Italic _text_ (avoid matching inside words like some_var_name)
    text = re.sub(r'(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])', r'<i>\1</i>', text)

    # 9. Strikethrough ~~text~~
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)

    # 10. Bullet lists - item -> • item
    text = re.sub(r'^[-*]\s+', '• ', text, flags=re.MULTILINE)

    # 11. Restore inline code with HTML tags
    for i, code in enumerate(inline_codes):
        # Escape HTML in code content
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00IC{i}\x00", f"<code>{escaped}</code>")

    # 12. Restore code blocks with HTML tags
    for i, code in enumerate(code_blocks):
        # Escape HTML in code content
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00CB{i}\x00", f"<pre><code>{escaped}</code></pre>")

    return text


def _build_user_message(message_id: str, text: str, **kwargs) -> dict:
    """
    构建 user 消息对象
    
    Args:
        message_id: 消息唯一 ID
        text: 消息文本内容
        **kwargs: 其他业务相关字段，如 location、image 等
    
    Returns:
        dict: 包含通用字段和业务字段的消息对象
    """
    request = {
        "id": message_id,
        "type": "user",
        "text": text
    }
    # 合并其他业务字段
    request.update(kwargs)
    return request


class TelegramBot:
    """Telegram 机器人封装类"""
    
    def __init__(self, token: str, ws_url: str = "ws://localhost:4567"):
        """初始化 Telegram Bot
        
        Args:
            token: Telegram Bot Token
            ws_url: WebSocket 服务器地址
        """
        self.token = token
        self.ws_url = ws_url
        self.application: Application | None = None
        self.websocket: websockets.WebSocketClientProtocol | None = None
        self._ws_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        # 存储消息 ID 到 chat_id 的映射
        self._message_map: dict[str, int] = {}
        # 存储每个消息 ID 累积的响应内容
        self._response_buffer: dict[str, str] = {}
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /start 命令"""
        user = update.effective_user
        await update.message.reply_text(
            f"你好 {user.first_name}！\n\n"
            "我是一个智能助手机器人。\n"
            "发送任意消息给我，我会帮你处理。\n\n"
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /help 命令"""
        await update.message.reply_text(
            "帮助信息：\n\n"
            "/start - 启动机器人\n"
            "/help - 查看此帮助信息\n"
            "/stop - 停止机器人\n\n"
            "直接发送文本消息，我会使用 AI 助手回复你。"
        )

    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /stop 命令"""
        logger.info(f"收到停止命令，来自用户: {update.effective_user.id}")
        await update.message.reply_text("机器人正在停止...")
        self._shutdown_event.set()
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理普通文本消息"""
        user_message = update.message.text
        user = update.effective_user
        logger.info(f"收到消息来自 {user.first_name} ({user.id}): {user_message}")
        
        # 检查 WebSocket 连接是否可用
        if not self.websocket:
            logger.error("WebSocket 未连接")
            await update.message.reply_text("抱歉，服务暂时不可用，请稍后再试。")
            return
        
        try:
            # 生成唯一消息 ID
            message_id = str(uuid.uuid4())
            
            # 保存消息 ID 到 chat_id 的映射
            self._message_map[message_id] = update.effective_chat.id
            
            # 构建消息格式
            request = _build_user_message(message_id, user_message)
            
            # 发送到 WebSocket 服务器
            await self.websocket.send(json.dumps(request, ensure_ascii=False))
            logger.info(f"已发送消息到 WebSocket [{message_id}]: {user_message}")
            
        except Exception as e:
            logger.exception(f"发送消息到 WebSocket 失败: {e}")
            await update.message.reply_text(f"处理失败: {str(e)}")
    
    async def handle_location(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理位置消息"""
        location = update.message.location
        user = update.effective_user
        logger.info(f"收到位置消息来自 {user.first_name} ({user.id}): ({location.latitude}, {location.longitude})")
        
        # 检查 WebSocket 连接是否可用
        if not self.websocket:
            logger.error("WebSocket 未连接")
            await update.message.reply_text("抱歉，服务暂时不可用，请稍后再试。")
            return
        
        try:
            # 生成唯一消息 ID
            message_id = str(uuid.uuid4())
            
            # 保存消息 ID 到 chat_id 的映射
            self._message_map[message_id] = update.effective_chat.id
            
            # 构建消息格式（包含位置信息）
            request = _build_user_message(
                message_id,
                f"用户发送了位置: 纬度 {location.latitude}, 经度 {location.longitude}",
                location={
                    "latitude": location.latitude,
                    "longitude": location.longitude
                }
            )
            
            # 发送到 WebSocket 服务器
            await self.websocket.send(json.dumps(request, ensure_ascii=False))
            logger.info(f"已发送位置消息到 WebSocket [{message_id}]: ({location.latitude}, {location.longitude})")
            
        except Exception as e:
            logger.exception(f"发送位置消息到 WebSocket 失败: {e}")
            await update.message.reply_text(f"处理失败: {str(e)}")
        
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理错误"""
        logger.error(f"更新 {update} 导致错误 {context.error}")
    
    async def _websocket_receiver(self) -> None:
        """WebSocket 消息接收循环"""
        try:
            logger.info(f"正在连接 WebSocket 服务器: {self.ws_url}")
            async with websockets.connect(self.ws_url) as websocket:
                self.websocket = websocket
                logger.info("WebSocket 连接成功")
                
                async for message in websocket:
                    try:
                        # 解析 JSON 响应
                        response = json.loads(message)
                        message_id = response.get("id", "")
                        msg_type = response.get("type", "")
                        
                        logger.info(f"[WebSocket 收到消息] ID={message_id}, type={msg_type}")
                        
                        # 检查消息 ID 是否存在映射
                        if message_id not in self._message_map:
                            logger.warning(f"未找到消息 ID 映射: {message_id}")
                            continue
                        
                        chat_id = self._message_map[message_id]
                        
                        if msg_type == "start":
                            # 开始接收，初始化缓冲区
                            self._response_buffer[message_id] = ""
                            
                        elif msg_type == "chunk":
                            # 累积响应片段
                            chunk = response.get("chunk", "")
                            if message_id not in self._response_buffer:
                                self._response_buffer[message_id] = ""
                            self._response_buffer[message_id] += chunk
                            
                        elif msg_type == "end":
                            # 结束，发送完整响应
                            full_response = _markdown_to_telegram_html(self._response_buffer.get(message_id, ""))
                            if full_response:
                                await self.application.bot.send_message(
                                    chat_id=chat_id,
                                    text=full_response,
                                    parse_mode="HTML"
                                )
                                logger.info(f"已发送完整响应给用户 {chat_id}")
                            else:
                                await self.application.bot.send_message(
                                    chat_id=chat_id,
                                    text="(无响应内容)"
                                )
                            
                            # 清理缓存
                            self._response_buffer.pop(message_id, None)
                            self._message_map.pop(message_id, None)
                            
                        elif msg_type == "error":
                            # 错误响应
                            error_msg = response.get("error", "未知错误")
                            await self.application.bot.send_message(
                                chat_id=chat_id,
                                text=f"❌ 错误: {error_msg}"
                            )
                            logger.error(f"处理消息 {message_id} 时出错: {error_msg}")
                            
                            # 清理缓存
                            self._response_buffer.pop(message_id, None)
                            self._message_map.pop(message_id, None)
                            
                    except json.JSONDecodeError as e:
                        logger.error(f"JSON 解析失败: {e}, 原始消息: {message}")
                    except Exception as e:
                        logger.exception(f"处理 WebSocket 消息时出错: {e}")
                
                # async for 循环正常结束（服务器关闭连接）
                logger.info("WebSocket 连接已正常关闭")
                self._shutdown_event.set()
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket 连接已关闭")
            # WebSocket 断开时，触发机器人停止
            self._shutdown_event.set()
        except Exception as e:
            logger.exception(f"WebSocket 连接错误: {e}")
            # WebSocket 异常时，触发机器人停止
            self._shutdown_event.set()
        finally:
            self.websocket = None
    
    def setup_handlers(self) -> None:
        """设置所有命令和消息处理器"""
        if not self.application:
            raise RuntimeError("Application 未初始化")
        
        # 注册命令处理器
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("stop", self.stop_command))
        
        # 注册消息处理器（处理所有文本消息）
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )
        
        # 注册位置消息处理器
        self.application.add_handler(
            MessageHandler(filters.LOCATION, self.handle_location)
        )
        
        # 注册错误处理器
        self.application.add_error_handler(self.error_handler)
    
    async def start_polling(self) -> None:
        """启动机器人（使用 polling 模式）"""
        # 创建 Application
        self.application = Application.builder().token(self.token).build()
        
        # 设置处理器
        self.setup_handlers()
        
        # 启动 WebSocket 客户端
        self._ws_task = asyncio.create_task(self._websocket_receiver())
        
        # 启动机器人
        logger.info("Telegram 机器人启动中...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        
        logger.info("Telegram 机器人运行中，按 Ctrl+C 停止...")
        
        # 保持运行
        try:
            await self._shutdown_event.wait()
        except (KeyboardInterrupt, SystemExit):
            logger.info("收到停止信号")
        finally:
            await self.stop()
    
    async def stop(self) -> None:
        """停止机器人"""
        # 停止 WebSocket 连接
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            logger.info("WebSocket 连接已关闭")

        if self.websocket and not self.websocket.closed:
            await self.websocket.close()

        # 停止 Telegram Bot
        if self.application:
            logger.info("正在停止 Telegram 机器人...")
            if self.application.updater:
                await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
            logger.info("Telegram 机器人已停止")
    
    def run(self) -> None:
        """同步方式运行机器人（blocking）"""
        try:
            asyncio.run(self.start_polling())
        except KeyboardInterrupt:
            logger.info("机器人已停止")

def main() -> None:
    """主函数"""
    # 从环境变量读取 Telegram Bot Token
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("请设置环境变量 TELEGRAM_BOT_TOKEN")
        return
    
    # 创建并运行机器人
    bot = TelegramBot(token)
    bot.run()


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    main()
