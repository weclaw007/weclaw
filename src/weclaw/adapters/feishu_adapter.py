"""飞书适配器 - 将飞书事件转发到 Agent 并将回复发回飞书。

v3 重构：
- 飞书 API 封装移至 FeishuClient（feishu_client.py）
- Agent 初始化使用 AgentRuntime（agent/runtime.py）
- message 工具通过 FeishuMessageTransport 实现 MessageTransport 协议
- 所有同步飞书 API 调用通过 asyncio.to_thread 异步化
- FeishuAdapter 只关注消息分发和生命周期管理

v4：继承 BaseAdapter，统一适配器接口（adapter_name / close / stop）
"""

import asyncio
import json
import logging
import os
from pathlib import Path

import certifi

# 修复 macOS SSL 证书验证
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

import lark_oapi as lark

from weclaw.adapters.base import BaseAdapter
from weclaw.adapters.feishu_client import FeishuClient, FeishuMessageTransport

logger = logging.getLogger(__name__)


class FeishuAdapter(BaseAdapter):
    """飞书 Bot 适配器 - 通过飞书长连接接收事件，直接调用 Agent 处理。

    职责：
    1. 飞书 WebSocket 长连接管理（start/stop）
    2. 消息类型分发（文本/位置/媒体）
    3. 通过 BaseAdapter.AgentRuntime 管理 Agent 生命周期
    """

    # 飞书消息类型 → 统一媒体类型映射
    _FEISHU_MEDIA_MAP: dict[str, str] = {"image": "image", "audio": "audio", "media": "video"}

    def __init__(self, app_id: str, app_secret: str) -> None:
        self._client = FeishuClient(app_id, app_secret)
        self._lark_ws_client: lark.ws.Client | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None
        # 先构建 transport，再传给 super().__init__
        greeting_chat_id = os.getenv("LARK_GREETING_CHAT_ID", "")
        transport = FeishuMessageTransport(self._client, greeting_chat_id)
        super().__init__(adapter_name="feishu", message_transport=transport)

    @property
    def _greeting_chat_id(self) -> str:
        """工具消息交互的默认会话 ID"""
        return os.getenv("LARK_GREETING_CHAT_ID", "")

    # ── 消息处理 ──────────────────────────────────────────────

    def _handle_receive_message(self, data: lark.im.v1.P2ImMessageReceiveV1) -> None:
        """处理飞书消息事件（由 lark.ws.Client 在子线程回调）。"""
        if not self._event_loop:
            logger.error("事件循环未初始化")
            return
        asyncio.run_coroutine_threadsafe(
            self._async_handle_message(data),
            self._event_loop,
        )

    async def _async_handle_message(self, data: lark.im.v1.P2ImMessageReceiveV1) -> None:
        """异步处理飞书消息"""
        try:
            event = data.event
            message = event.message
            msg_type = message.message_type
            chat_id = message.chat_id

            logger.info(
                f"收到飞书消息: type={msg_type}, chat_id={chat_id}, "
                f"sender={event.sender.sender_id.open_id}"
            )

            content = json.loads(message.content)

            # 命令处理（即使 stopped 也要响应 /start /stop /help）
            if msg_type == "text":
                text = content.get("text", "").strip()
                if text in ("/stop", "/start", "/help"):
                    await self._handle_command(chat_id, text)
                    return

            # 统一停止态检查（命令之外的所有消息类型）
            if self._stopped:
                await asyncio.to_thread(
                    self._client.send_reply, chat_id, self._STOPPED_REPLY,
                )
                return

            # 位置消息
            if msg_type == "location":
                await self._handle_location_message(chat_id, content)
                return

            # 媒体消息
            if msg_type in self._FEISHU_MEDIA_MAP:
                await self._handle_media_message(
                    chat_id, message.message_id, content, self._FEISHU_MEDIA_MAP[msg_type]
                )
                return

            # 非文本消息
            if msg_type != "text":
                await asyncio.to_thread(
                    self._client.send_reply, chat_id,
                    "暂时只支持文本消息、图片消息、语音消息、视频消息和位置消息哦~",
                )
                return

            text = content.get("text", "").strip()
            if not text:
                return

            # 调用 Agent 获取回复
            reply = await self.ask_agent(text)
            if reply:
                await asyncio.to_thread(self._client.send_reply, chat_id, reply)
            else:
                await asyncio.to_thread(self._client.send_reply, chat_id, "(无响应内容)")

        except Exception as e:
            logger.exception(f"处理飞书消息时出错: {e}")

    async def _handle_command(self, chat_id: str, text: str) -> None:
        """处理命令消息（/start /stop /help）"""
        if text == "/stop":
            self._stopped = True
            await asyncio.to_thread(
                self._client.send_reply, chat_id,
                "机器人已停止接收消息。\n发送 /start 可重新启动。",
            )
        elif text == "/start":
            if self._stopped:
                self._stopped = False
                await asyncio.to_thread(
                    self._client.send_reply, chat_id,
                    "欢迎回来！机器人已重新启动，可以继续发送消息了。",
                )
            else:
                await asyncio.to_thread(
                    self._client.send_reply, chat_id,
                    "你好！我是智能助手机器人。\n发送任意消息给我，我会帮你处理。",
                )
        elif text == "/help":
            await asyncio.to_thread(
                self._client.send_reply, chat_id,
                "帮助信息：\n\n"
                "/start - 启动机器人\n"
                "/help - 查看此帮助信息\n"
                "/stop - 停止机器人\n\n"
                "直接发送文本消息，我会使用 AI 助手回复你。",
            )

    async def _handle_location_message(self, chat_id: str, content: dict) -> None:
        """处理位置消息（调用方已做 stopped 检查）"""
        latitude = content.get("latitude", "")
        longitude = content.get("longitude", "")
        name = content.get("name", "")

        if not latitude or not longitude:
            await asyncio.to_thread(self._client.send_reply, chat_id, "无法解析位置信息。")
            return

        location_name = f"({name})" if name else ""
        prompt = f"用户发送了位置{location_name}: 纬度 {latitude}, 经度 {longitude}"

        reply = await self.ask_agent(prompt)
        if reply:
            await asyncio.to_thread(self._client.send_reply, chat_id, reply)

    async def _handle_media_message(
        self, chat_id: str, feishu_message_id: str, content: dict, media_type: str,
    ) -> None:
        """处理媒体消息（图片/音频/视频，调用方已做 stopped 检查）"""
        config = FeishuClient.MEDIA_TYPE_CONFIG[media_type]
        display_name = config["display_name"]
        content_key = config["content_key"]

        resource_key = content.get(content_key, "")
        if not resource_key:
            await asyncio.to_thread(
                self._client.send_reply, chat_id, f"无法解析{display_name}消息。",
            )
            return

        # 下载媒体文件（同步 I/O，放到线程池）
        file_path = await asyncio.to_thread(
            self._client.download_resource, feishu_message_id, resource_key, media_type,
        )
        if not file_path:
            await asyncio.to_thread(
                self._client.send_reply, chat_id, f"{display_name}下载失败，请稍后再试。",
            )
            return

        # 通过 media_processor 预处理后调用 Agent
        media_payload = {media_type: [{"type": "file", "data": file_path}]}
        try:
            reply = await self.ask_agent_with_media(media_payload)
            if reply:
                await asyncio.to_thread(self._client.send_reply, chat_id, reply)
            else:
                await asyncio.to_thread(self._client.send_reply, chat_id, "(无响应内容)")
        except Exception as e:
            logger.exception(f"处理{display_name}消息失败: {e}")
            await asyncio.to_thread(
                self._client.send_reply, chat_id, f"{display_name}处理失败，请稍后再试。",
            )

    # ── 生命周期管理 ──────────────────────────────────────────

    async def start(self) -> None:
        """启动飞书适配器。"""
        self._event_loop = asyncio.get_running_loop()

        # 读取飞书技能 SKILL.md 作为 inject prompt
        inject_prompt = ""
        skill_md_path = Path(__file__).resolve().parent.parent / "skills" / "feishu" / "SKILL.md"
        if skill_md_path.exists():
            inject_prompt = skill_md_path.read_text(encoding="utf-8")

        # 通过 BaseAdapter 统一初始化 Agent
        await self.initialize_agent(inject_prompt=inject_prompt)

        # 构建飞书事件处理器
        event_handler = lark.EventDispatcherHandler.builder(
            "", ""  # 长连接模式无需加密和验证 token
        ).register_p2_im_message_receive_v1(
            self._handle_receive_message
        ).build()

        self._lark_ws_client = lark.ws.Client(
            self._client.app_id,
            self._client.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        logger.info("飞书适配器启动中...")

        # lark_oapi.ws.client 在模块级别获取 event loop 并在 start() 中用
        # loop.run_until_complete()，和我们的主 event loop 冲突。
        # 解决：在子线程里创建新 loop 并 patch 到 SDK 模块。
        def _run_lark_ws():
            import lark_oapi.ws.client as _ws_mod
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            _ws_mod.loop = new_loop  # monkey-patch SDK 的模块级 loop
            try:
                self._lark_ws_client.start()
            finally:
                new_loop.close()

        await asyncio.to_thread(_run_lark_ws)

    async def stop(self) -> None:
        """停止飞书适配器"""
        logger.info("飞书适配器停止中...")
        await self.close()
        logger.info("飞书适配器已停止")
