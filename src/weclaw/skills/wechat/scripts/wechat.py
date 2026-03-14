import asyncio
import json
import logging
import os
import re
import uuid
import websockets
from pathlib import Path

# 配置日志
logging.basicConfig(
    format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def _build_user_message(message_id: str, text: str) -> dict:
    """构建用户消息格式， 给大模型分析
    
    Args:
        message_id: 消息 ID
        content: 消息内容
        location: 位置信息（可选）
    
    Returns:
        消息字典
    """
    message = {
        "id": message_id,
        "type": "user",
        "text": text
    }

    return message


def _build_system_message(**kwargs) -> dict:
    """构建工具消息格式

    Args:
        **kwargs: 可变参数，用于传递工具调用相关的数据

    Returns:
        消息字典
    """
    message = {
        "type": "system"
    }

    # 将可变参数添加到消息中
    message.update(kwargs)

    return message

def _build_tool_message(message_id: str, **kwargs) -> dict:
    """构建工具消息格式

    Args:
        message_id: 消息 ID
        **kwargs: 可变参数，用于传递工具调用相关的数据

    Returns:
        消息字典
    """
    message = {
        "id": message_id,
        "type": "tool"
    }
    
    # 将可变参数添加到消息中
    message.update(kwargs)

    return message

class WechatBot:
    """Wechat WebSocket 客户端封装类"""
    
    def __init__(self, ws_url: str = "ws://localhost:4567"):
        """初始化 Wechat WebSocket 客户端
        
        Args:
            ws_url: WebSocket 服务器地址
        """
        self.ws_url = ws_url
        self.websocket: websockets.WebSocketClientProtocol | None = None
        self._ws_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        # 存储每个消息 ID 累积的响应内容
        self._response_buffer: dict[str, str] = {}

    # 回显给用户的消息
    async def _handle_stream_message(self, message_id: str, msg_type: str, response: dict) -> None:
        """处理流式消息（start、chunk、end类型）
        
        Args:
            message_id: 消息 ID
            msg_type: 消息类型
            response: 响应数据
        """
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
            # 结束，记录完整响应
            full_response = self._response_buffer.get(message_id, "")
            logger.info(f"已处理完整响应 [{message_id}]: {full_response}")
            
            # 清理缓存
            self._response_buffer.pop(message_id, None)
    
    async def _handle_unknown_action(self, message_id: str, action: str) -> dict:
        """处理未知action请求
        
        Args:
            message_id: 消息 ID
            action: 未知的action类型
            
        Returns:
            构建的错误消息
        """
        logger.warning(f"未知的action类型: {action}")
        return _build_tool_message(
            message_id,
            action="unknown",
            error=f"未知的action类型: {action}"
        )
    
    async def _handle_tool_message(self, message_id: str, response: dict) -> None:
        """处理工具调用结果消息
        
        Args:
            message_id: 消息 ID
            response: 响应数据
        """
        # 实现和微信的交互，然后将数据返回给大模型，比如将请求 post给微信接口，获取结果后再发送回大模型
       
        
        await self.websocket.send(json.dumps(reply_message))
        logger.info(f"已发送工具调用结果消息 [{message_id}], action={action}")

        
    async def _websocket_receiver(self) -> None:
        """WebSocket 消息接收循环"""
        try:
            logger.info(f"正在连接 WebSocket 服务器: {self.ws_url}")
            async with websockets.connect(self.ws_url) as websocket:
                self.websocket = websocket
                # 注入系统提示词,读取 SKILL.md 文件
                skill_md_path = Path(__file__).parent.parent / "SKILL.md"
                with open(skill_md_path, "r", encoding="utf-8") as f:
                    prompt = f.read()


                await self.websocket.send(json.dumps(_build_system_message(
                    action = "prompt",
                    text = prompt
                )))


                logger.info("WebSocket 连接成功")
                async for message in websocket:
                    try:
                        # 解析 JSON 响应
                        response = json.loads(message)
                        message_id = response.get("id", "")
                        msg_type = response.get("type", "")
                        
                        logger.info(f"[WebSocket 收到消息] ID={message_id}, type={msg_type}")
                        
                        # 处理流式消息类型
                        if msg_type in ["start", "chunk", "end"]:
                            await self._handle_stream_message(message_id, msg_type, response)
                        elif msg_type == "tool":
                            await self._handle_tool_message(message_id, response)
                        elif msg_type == "error":
                            # 错误响应
                            error_msg = response.get("error", "未知错误")
                            logger.error(f"处理消息 {message_id} 时出错: {error_msg}")
                            
                            # 清理缓存
                            self._response_buffer.pop(message_id, None)
                            
                    except json.JSONDecodeError as e:
                        logger.error(f"JSON 解析失败: {e}, 原始消息: {message}")
                    except Exception as e:
                        logger.exception(f"处理 WebSocket 消息时出错: {e}")
                
                # async for 循环正常结束（服务器关闭连接）
                logger.info("WebSocket 连接已正常关闭")
                self._shutdown_event.set()
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket 连接已关闭")
            self._shutdown_event.set()
        except Exception as e:
            logger.exception(f"WebSocket 连接错误: {e}")
            self._shutdown_event.set()
        finally:
            self.websocket = None
    
    async def start(self) -> None:
        """启动 WebSocket 客户端"""
        self._ws_task = asyncio.create_task(self._websocket_receiver())
        
        logger.info("Wechat WebSocket 客户端启动中...")
        
        # 等待连接建立
        while self.websocket is None and not self._shutdown_event.is_set():
            await asyncio.sleep(0.1)
        
        if self.websocket:
            logger.info("Wechat WebSocket 客户端运行中...")
    
    async def stop(self) -> None:
        """停止 WebSocket 客户端"""
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
            logger.info("Wechat WebSocket 客户端已停止")
    
    def run(self) -> None:
        """同步方式运行客户端（blocking）"""
        try:
            asyncio.run(self._run_async())
        except KeyboardInterrupt:
            logger.info("客户端已停止")
    
    async def _run_async(self) -> None:
        """异步运行客户端"""
        await self.start()
        
        try:
            # 保持运行直到收到停止信号
            await self._shutdown_event.wait()
        except (KeyboardInterrupt, SystemExit):
            logger.info("收到停止信号")
        finally:
            await self.stop()


def main() -> None:
    """主函数 - 启动异步 WebSocket 连接"""
    
    async def run_websocket() -> None:
        """运行 WebSocket 客户端"""
        # 创建 WebSocket 客户端
        bot = WechatBot()
        
        # 启动客户端
        await bot.start()
        
        try:
            logger.info("WebSocket 连接已启动，等待消息处理...")
            
            # 保持运行直到收到停止信号
            await bot._shutdown_event.wait()
            
        except (KeyboardInterrupt, SystemExit):
            logger.info("收到停止信号")
        finally:
            await bot.stop()
    
    # 运行 WebSocket 客户端
    asyncio.run(run_websocket())


if __name__ == "__main__":
    main()
