import asyncio
import json
import logging
import os
import ssl
import tempfile
import uuid
import threading
import websockets
from pathlib import Path

# 修复 macOS 上 SSL 证书验证失败的问题
import certifi
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

import lark_oapi as lark
from lark_oapi.api.im.v1 import *

from weclaw.utils.message import build_user_message, build_system_message, build_tool_message

# 配置日志
logging.basicConfig(
    format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class FeishuBot:
    """飞书机器人封装类"""

    def __init__(self, app_id: str, app_secret: str, ws_url: str = "ws://localhost:4567"):
        """初始化飞书 Bot

        Args:
            app_id: 飞书应用 App ID
            app_secret: 飞书应用 App Secret
            ws_url: WebSocket 服务器地址
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self.ws_url = ws_url

        # lark 客户端
        self.lark_client = lark.Client.builder() \
            .app_id(app_id) \
            .app_secret(app_secret) \
            .log_level(lark.LogLevel.INFO) \
            .build()

        # WebSocket 相关
        self.websocket: websockets.WebSocketClientProtocol | None = None
        self._shutdown_event: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

        # 机器人是否处于停止状态
        self._stopped = False

        # 存储消息 ID 到飞书 message_id 的映射（用于回复）
        self._message_map: dict[str, str] = {}
        # 存储每个消息 ID 累积的响应内容
        self._response_buffer: dict[str, str] = {}
        # 存储消息 ID 到 chat_id 的映射
        self._chat_map: dict[str, str] = {}

    @property
    def _greeting_chat_id(self) -> str:
        """获取用于工具消息交互的默认会话 ID"""
        return os.getenv("LARK_GREETING_CHAT_ID", "")

    def _send_feishu_reply(self, chat_id: str, text: str) -> None:
        """发送飞书消息

        Args:
            chat_id: 飞书会话 ID
            text: 消息文本
        """
        try:
            # 构建富文本消息内容
            content = json.dumps({"text": text})

            request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("text")
                    .content(content)
                    .build()
                ).build()

            response = self.lark_client.im.v1.message.create(request)

            if not response.success():
                logger.error(
                    f"发送飞书消息失败: code={response.code}, msg={response.msg}, "
                    f"log_id={response.get_log_id()}"
                )
            else:
                logger.info(f"已发送飞书消息到会话 {chat_id}")

        except Exception as e:
            logger.exception(f"发送飞书消息异常: {e}")

    def _upload_image(self, image_path: str) -> str | None:
        """上传图片到飞书，返回 image_key

        Args:
            image_path: 本地图片文件路径

        Returns:
            image_key 字符串，上传失败返回 None
        """
        try:
            # 展开 ~ 为用户主目录
            image_path = os.path.expanduser(image_path)

            if not os.path.isfile(image_path):
                logger.error(f"图片文件不存在: {image_path}")
                return None

            with open(image_path, "rb") as f:
                request = CreateImageRequest.builder() \
                    .request_body(
                        CreateImageRequestBody.builder()
                        .image_type("message")
                        .image(f)
                        .build()
                    ).build()

                response = self.lark_client.im.v1.image.create(request)

            if not response.success():
                logger.error(
                    f"上传图片失败: code={response.code}, msg={response.msg}, "
                    f"log_id={response.get_log_id()}"
                )
                return None

            image_key = response.data.image_key
            logger.info(f"图片上传成功: {image_path} -> {image_key}")
            return image_key

        except Exception as e:
            logger.exception(f"上传图片异常: {e}")
            return None

    # 文件类型映射：文件后缀 -> 飞书 file_type
    _FILE_TYPE_MAP = {
        ".opus": "opus", ".mp4": "mp4", ".pdf": "pdf",
        ".doc": "doc", ".docx": "doc",
        ".xls": "xls", ".xlsx": "xls",
        ".ppt": "ppt", ".pptx": "ppt",
    }

    def _upload_file(self, file_path: str) -> str | None:
        """上传文件到飞书，返回 file_key

        Args:
            file_path: 本地文件路径

        Returns:
            file_key 字符串，上传失败返回 None
        """
        try:
            # 展开 ~ 为用户主目录
            file_path = os.path.expanduser(file_path)

            if not os.path.isfile(file_path):
                logger.error(f"文件不存在: {file_path}")
                return None

            file_name = os.path.basename(file_path)
            suffix = os.path.splitext(file_name)[1].lower()
            file_type = self._FILE_TYPE_MAP.get(suffix, "stream")

            with open(file_path, "rb") as f:
                request = CreateFileRequest.builder() \
                    .request_body(
                        CreateFileRequestBody.builder()
                        .file_type(file_type)
                        .file_name(file_name)
                        .file(f)
                        .build()
                    ).build()

                response = self.lark_client.im.v1.file.create(request)

            if not response.success():
                logger.error(
                    f"上传文件失败: code={response.code}, msg={response.msg}, "
                    f"log_id={response.get_log_id()}"
                )
                return None

            file_key = response.data.file_key
            logger.info(f"文件上传成功: {file_path} -> {file_key}")
            return file_key

        except Exception as e:
            logger.exception(f"上传文件异常: {e}")
            return None

    def _send_feishu_file(self, chat_id: str, file_path: str) -> bool:
        """发送文件消息到飞书

        Args:
            chat_id: 飞书会话 ID
            file_path: 本地文件路径

        Returns:
            是否发送成功
        """
        file_key = self._upload_file(file_path)
        if not file_key:
            logger.error(f"文件发送失败: 无法上传文件 {file_path}")
            return False

        try:
            file_name = os.path.basename(os.path.expanduser(file_path))
            content = json.dumps({"file_key": file_key, "file_name": file_name})

            request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("file")
                    .content(content)
                    .build()
                ).build()

            response = self.lark_client.im.v1.message.create(request)

            if not response.success():
                logger.error(
                    f"发送文件消息失败: code={response.code}, msg={response.msg}, "
                    f"log_id={response.get_log_id()}"
                )
                return False

            logger.info(f"已发送文件消息到会话 {chat_id}: {file_path}")
            return True

        except Exception as e:
            logger.exception(f"发送文件消息异常: {e}")
            return False

    def _send_feishu_image(self, chat_id: str, image_path: str) -> bool:
        """发送图片消息到飞书

        Args:
            chat_id: 飞书会话 ID
            image_path: 本地图片文件路径

        Returns:
            是否发送成功
        """
        image_key = self._upload_image(image_path)
        if not image_key:
            logger.error(f"图片发送失败: 无法上传图片 {image_path}")
            return False

        try:
            content = json.dumps({"image_key": image_key})

            request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("image")
                    .content(content)
                    .build()
                ).build()

            response = self.lark_client.im.v1.message.create(request)

            if not response.success():
                logger.error(
                    f"发送图片消息失败: code={response.code}, msg={response.msg}, "
                    f"log_id={response.get_log_id()}"
                )
                return False

            logger.info(f"已发送图片消息到会话 {chat_id}: {image_path}")
            return True

        except Exception as e:
            logger.exception(f"发送图片消息异常: {e}")
            return False

    def _download_audio_resource(self, feishu_message_id: str, file_key: str) -> str | None:
        """从飞书下载音频资源到本地临时文件

        Args:
            feishu_message_id: 飞书消息 ID
            file_key: 音频文件的 file_key

        Returns:
            本地临时文件路径，下载失败返回 None
        """
        try:
            request = GetMessageResourceRequest.builder() \
                .message_id(feishu_message_id) \
                .file_key(file_key) \
                .type("file") \
                .build()

            response = self.lark_client.im.v1.message_resource.get(request)

            if not response.success():
                logger.error(
                    f"下载音频资源失败: code={response.code}, msg={response.msg}, "
                    f"log_id={response.get_log_id()}"
                )
                return None

            # 将音频数据写入临时文件
            # 飞书音频消息格式为 opus，保存为 .opus 后缀
            tmp_dir = os.path.join(tempfile.gettempdir(), "feishu_audio")
            os.makedirs(tmp_dir, exist_ok=True)
            tmp_path = os.path.join(tmp_dir, f"{file_key}.opus")

            with open(tmp_path, "wb") as f:
                f.write(response.file.read())

            logger.info(f"音频资源已下载: {feishu_message_id}/{file_key} -> {tmp_path}")
            return tmp_path

        except Exception as e:
            logger.exception(f"下载音频资源异常: {e}")
            return None

    def _handle_audio_message(self, chat_id: str, feishu_message_id: str, content: dict) -> None:
        """处理音频消息

        从飞书下载音频文件，通过 WebSocket 以文件路径方式发送给大模型进行语音识别。

        Args:
            chat_id: 飞书会话 ID
            feishu_message_id: 飞书消息 ID（用于下载资源）
            content: 飞书音频消息内容，格式如 {"file_key": "..."}
        """
        # 停止状态下不处理消息
        if self._stopped:
            self._send_feishu_reply(chat_id, "机器人已停止，发送 /start 重新启动。")
            return

        file_key = content.get("file_key", "")
        if not file_key:
            logger.error(f"音频消息缺少 file_key: {content}")
            self._send_feishu_reply(chat_id, "无法解析语音消息。")
            return

        # 下载音频文件
        audio_path = self._download_audio_resource(feishu_message_id, file_key)
        if not audio_path:
            self._send_feishu_reply(chat_id, "语音消息下载失败，请稍后再试。")
            return

        # 检查 WebSocket 连接
        if not self.websocket:
            self._send_feishu_reply(chat_id, "抱歉，服务暂时不可用，请稍后再试。")
            return

        try:
            # 生成唯一消息 ID
            message_id = str(uuid.uuid4())

            # 保存映射
            self._message_map[message_id] = feishu_message_id
            self._chat_map[message_id] = chat_id

            # 构建消息，audio 字段使用列表格式
            request = build_user_message(
                message_id,
                "",
                audio=[{"type": "file", "data": audio_path}]
            )

            # 发送到 WebSocket
            if self._loop and self.websocket:
                future = asyncio.run_coroutine_threadsafe(
                    self.websocket.send(json.dumps(request, ensure_ascii=False)),
                    self._loop
                )
                future.result(timeout=30)  # 语音文件较大，超时时间适当延长
                logger.info(f"已发送语音消息到 WebSocket [{message_id}]: {audio_path}")
            else:
                logger.error("WebSocket 连接不可用")
                self._send_feishu_reply(chat_id, "抱歉，服务暂时不可用，请稍后再试。")

        except Exception as e:
            logger.exception(f"发送语音消息到 WebSocket 失败: {e}")

    async def _reply_tool_message(self, message_id: str, status: str, **kwargs) -> None:
        """通过 WebSocket 回复工具消息结果给大模型

        Args:
            message_id: 原始工具消息的 ID
            status: 执行状态，如 "success" 或 "error"
            **kwargs: 其他业务字段，如 error_msg 等
        """
        reply = build_tool_message(message_id, status=status, **kwargs)
        if self.websocket:
            try:
                await self.websocket.send(json.dumps(reply, ensure_ascii=False))
                logger.info(f"已回复工具消息: id={message_id}, status={status}")
            except Exception as e:
                logger.error(f"回复工具消息失败: {e}")
        else:
            logger.error("WebSocket 连接不可用，无法回复工具消息")

    async def _handle_tool_message(self, response: dict) -> None:
        """处理大模型发送过来的工具消息

        工具消息用来和 LARK_GREETING_CHAT_ID 标识的用户交互。
        根据 action 字段分发到不同的处理方法，执行结果通过 WebSocket 回复给大模型。

        Args:
            response: WebSocket 收到的工具消息，格式如:
                {"id": "...", "type": "tool", "action": "send_pic", "path": "xxx.png"}
        """
        chat_id = self._greeting_chat_id
        if not chat_id:
            logger.warning("未配置 LARK_GREETING_CHAT_ID，无法处理工具消息")
            return

        action = response.get("action", "")
        message_id = response.get("id", "")

        logger.info(f"处理工具消息: id={message_id}, action={action}")

        if action == "send_pic":
            # 发送图片
            path = response.get("path", "")
            if not path:
                logger.error(f"send_pic 缺少 path 参数: {response}")
                await self._reply_tool_message(message_id, "error", error_msg="缺少图片路径")
                return
            ok = self._send_feishu_image(chat_id, path)
            if ok:
                await self._reply_tool_message(message_id, "success", action=action, path=path)
            else:
                await self._reply_tool_message(message_id, "error", error_msg=f"图片发送失败: {path}")

        elif action == "send_text":
            # 发送文本消息
            text = response.get("text", "")
            if not text:
                logger.error(f"send_text 缺少 text 参数: {response}")
                await self._reply_tool_message(message_id, "error", error_msg="缺少文本内容")
                return
            self._send_feishu_reply(chat_id, text)
            await self._reply_tool_message(message_id, "success", action=action)

        elif action == "send_file":
            # 发送文件
            path = response.get("path", "")
            if not path:
                logger.error(f"send_file 缺少 path 参数: {response}")
                await self._reply_tool_message(message_id, "error", error_msg="缺少文件路径")
                return
            ok = self._send_feishu_file(chat_id, path)
            if ok:
                await self._reply_tool_message(message_id, "success", action=action, path=path)
            else:
                await self._reply_tool_message(message_id, "error", error_msg=f"文件发送失败: {path}")

        else:
            logger.warning(f"未知的工具消息 action: {action}, 完整消息: {response}")
            await self._reply_tool_message(message_id, "error", error_msg=f"不支持的操作: {action}")

    def _handle_receive_message(self, data: lark.im.v1.P2ImMessageReceiveV1) -> None:
        """处理接收到的飞书消息事件

        Args:
            data: 飞书消息事件数据
        """
        try:
            event = data.event
            message = event.message
            sender = event.sender

            # 获取消息内容
            msg_type = message.message_type
            chat_id = message.chat_id

            logger.info(
                f"收到飞书消息: type={msg_type}, chat_id={chat_id}, "
                f"sender={sender.sender_id.open_id}"
            )

            # 解析消息内容
            content = json.loads(message.content)

            # 处理位置消息
            if msg_type == "location":
                self._handle_location_message(chat_id, content)
                return

            # 处理音频消息
            if msg_type == "audio":
                self._handle_audio_message(chat_id, message.message_id, content)
                return

            # 除位置消息和音频消息外，目前只处理文本消息
            if msg_type != "text":
                self._send_feishu_reply(chat_id, "暂时只支持文本消息、语音消息和位置消息哦~")
                return

            text = content.get("text", "").strip()

            if not text:
                return

            # 处理命令
            if text == "/stop":
                self._stopped = True
                self._send_feishu_reply(chat_id, "机器人已停止接收消息。\n发送 /start 可重新启动。")
                logger.info("收到 /stop 命令，机器人已停止")
                return

            if text == "/start":
                if self._stopped:
                    self._stopped = False
                    self._send_feishu_reply(chat_id, "欢迎回来！机器人已重新启动，可以继续发送消息了。")
                    logger.info("收到 /start 命令，机器人已恢复")
                else:
                    self._send_feishu_reply(chat_id, "你好！我是智能助手机器人。\n发送任意消息给我，我会帮你处理。")
                return

            if text == "/help":
                self._send_feishu_reply(
                    chat_id,
                    "帮助信息：\n\n"
                    "/start - 启动机器人\n"
                    "/help - 查看此帮助信息\n"
                    "/stop - 停止机器人\n\n"
                    "直接发送文本消息，我会使用 AI 助手回复你。"
                )
                return

            # 停止状态下不处理消息
            if self._stopped:
                self._send_feishu_reply(chat_id, "机器人已停止，发送 /start 重新启动。")
                return

            # 发送到 WebSocket
            if not self.websocket:
                self._send_feishu_reply(chat_id, "抱歉，服务暂时不可用，请稍后再试。")
                return

            # 生成唯一消息 ID
            message_id = str(uuid.uuid4())

            # 保存映射
            self._message_map[message_id] = message.message_id
            self._chat_map[message_id] = chat_id

            # 构建消息并发送到 WebSocket
            request = build_user_message(message_id, text)

            if self._loop and self.websocket:
                future = asyncio.run_coroutine_threadsafe(
                    self.websocket.send(json.dumps(request, ensure_ascii=False)),
                    self._loop
                )
                future.result(timeout=10)
                logger.info(f"已发送消息到 WebSocket [{message_id}]: {text}")
            else:
                logger.error("WebSocket 连接不可用")
                self._send_feishu_reply(chat_id, "抱歉，服务暂时不可用，请稍后再试。")

        except Exception as e:
            logger.exception(f"处理飞书消息时出错: {e}")

    def _handle_location_message(self, chat_id: str, content: dict) -> None:
        """处理位置消息

        Args:
            chat_id: 飞书会话 ID
            content: 飞书位置消息内容，格式如 {"latitude": "...", "longitude": "...", "name": "..."}
        """
        # 停止状态下不处理消息
        if self._stopped:
            self._send_feishu_reply(chat_id, "机器人已停止，发送 /start 重新启动。")
            return

        latitude = content.get("latitude", "")
        longitude = content.get("longitude", "")
        name = content.get("name", "")

        if not latitude or not longitude:
            self._send_feishu_reply(chat_id, "无法解析位置信息。")
            return

        logger.info(f"收到位置消息: name={name}, lat={latitude}, lng={longitude}")

        # 检查 WebSocket 连接是否可用
        if not self.websocket:
            self._send_feishu_reply(chat_id, "抱歉，服务暂时不可用，请稍后再试。")
            return

        try:
            # 生成唯一消息 ID
            message_id = str(uuid.uuid4())

            # 保存映射
            self._message_map[message_id] = message_id
            self._chat_map[message_id] = chat_id

            # 构建消息格式（包含位置信息）
            location_name = f"({name})" if name else ""
            request = build_user_message(
                message_id,
                f"用户发送了位置{location_name}: 纬度 {latitude}, 经度 {longitude}",
            )

            # 发送到 WebSocket
            if self._loop and self.websocket:
                future = asyncio.run_coroutine_threadsafe(
                    self.websocket.send(json.dumps(request, ensure_ascii=False)),
                    self._loop
                )
                future.result(timeout=10)
                logger.info(f"已发送位置消息到 WebSocket [{message_id}]: ({latitude}, {longitude})")
            else:
                logger.error("WebSocket 连接不可用")
                self._send_feishu_reply(chat_id, "抱歉，服务暂时不可用，请稍后再试。")

        except Exception as e:
            logger.exception(f"发送位置消息到 WebSocket 失败: {e}")

    async def _websocket_receiver(self) -> None:
        """WebSocket 消息接收循环，支持断线自动重连"""
        while not self._shutdown_event.is_set():
            try:
                logger.info(f"正在连接 WebSocket 服务器: {self.ws_url}")
                async with websockets.connect(self.ws_url) as websocket:
                    self.websocket = websocket
                    logger.info("WebSocket 连接成功")

                    # 注入系统提示词，读取 SKILL.md 文件
                    skill_md_path = Path(__file__).parent.parent / "SKILL.md"
                    with open(skill_md_path, "r", encoding="utf-8") as f:
                        prompt = f.read()

                    await self.websocket.send(json.dumps(build_system_message(
                        action="prompt",
                        text=prompt
                    )))

                    async for message in websocket:
                        try:
                            response = json.loads(message)
                            message_id = response.get("id", "")
                            msg_type = response.get("type", "")

                            logger.info(f"[WebSocket 收到消息] ID={message_id}, type={msg_type}")

                            # tool 消息不需要 chat_map 映射，直接处理
                            if msg_type == "tool":
                                await self._handle_tool_message(response)
                                continue

                            # 检查消息 ID 是否存在映射
                            if message_id not in self._chat_map:
                                logger.warning(f"未找到消息 ID 映射: {message_id}")
                                continue

                            chat_id = self._chat_map[message_id]

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
                                full_response = self._response_buffer.get(message_id, "")
                                if full_response:
                                    # 飞书消息直接发送文本（飞书客户端会自动渲染 Markdown）
                                    self._send_feishu_reply(chat_id, full_response)
                                    logger.info(f"已发送完整响应给会话 {chat_id}")
                                else:
                                    self._send_feishu_reply(chat_id, "(无响应内容)")

                                # 清理缓存
                                self._response_buffer.pop(message_id, None)
                                self._message_map.pop(message_id, None)
                                self._chat_map.pop(message_id, None)

                            elif msg_type == "error":
                                # 错误响应
                                error_msg = response.get("error", "未知错误")
                                self._send_feishu_reply(chat_id, f"❌ 错误: {error_msg}")
                                logger.error(f"处理消息 {message_id} 时出错: {error_msg}")

                                # 清理缓存
                                self._response_buffer.pop(message_id, None)
                                self._message_map.pop(message_id, None)
                                self._chat_map.pop(message_id, None)

                        except json.JSONDecodeError as e:
                            logger.error(f"JSON 解析失败: {e}, 原始消息: {message}")
                        except Exception as e:
                            logger.exception(f"处理 WebSocket 消息时出错: {e}")

                    # async for 循环正常结束（服务器主动关闭连接）
                    logger.info("WebSocket 连接已被服务器关闭")

            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket 连接已断开")
            except Exception as e:
                logger.exception(f"WebSocket 连接错误: {e}")
            finally:
                self.websocket = None

            # 如果不是主动关闭，则等待 10 秒后重连
            if not self._shutdown_event.is_set():
                logger.info("将在 10 秒后尝试重新连接 WebSocket...")
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=10)
                except asyncio.TimeoutError:
                    pass

        logger.info("WebSocket 接收循环已退出")

    def _start_ws_loop(self) -> None:
        """在独立线程中启动 asyncio 事件循环，运行 WebSocket 接收器"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._shutdown_event = asyncio.Event()
        self._loop.run_until_complete(self._websocket_receiver())

    def run(self) -> None:
        """启动飞书机器人（blocking）"""
        logger.info("飞书机器人启动中...")

        # 在独立线程中启动 WebSocket 接收循环
        ws_thread = threading.Thread(target=self._start_ws_loop, daemon=True)
        ws_thread.start()

        # 构建飞书事件处理器
        event_handler = lark.EventDispatcherHandler.builder(
            "", ""  # 加密和验证 token，长连接模式可留空
        ).register_p2_im_message_receive_v1(
            self._handle_receive_message
        ).build()

        # 使用长连接（WebSocket）方式启动飞书客户端
        cli = lark.ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        logger.info("飞书机器人运行中，按 Ctrl+C 停止...")

        try:
            cli.start()
        except KeyboardInterrupt:
            logger.info("收到停止信号")
        finally:
            # 通知 WebSocket 线程停止
            if self._loop and self._shutdown_event:
                self._loop.call_soon_threadsafe(self._shutdown_event.set)
            ws_thread.join(timeout=5)
            logger.info("飞书机器人已停止")


def main() -> None:
    """主函数"""
    app_id = os.getenv("LARK_APP_ID")
    app_secret = os.getenv("LARK_APP_SECRET")

    if not app_id or not app_secret:
        logger.error("请设置环境变量 LARK_APP_ID 和 LARK_APP_SECRET")
        return

    bot = FeishuBot(app_id, app_secret)
    bot.run()


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    main()
