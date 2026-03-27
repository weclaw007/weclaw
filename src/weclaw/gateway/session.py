"""WebSocket 会话管理 - 每个连接一个 Session 实例。

v3 重构：
- Agent 初始化逻辑移至 AgentRuntime（agent/runtime.py）
- message 工具通过 WebSocketMessageTransport 实现 MessageTransport 协议
- Session 只负责 WebSocket 连接管理、消息分发、流式推送
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Dict

import websockets

from weclaw.agent.handlers import (
    BaseHandler, SkillHandler, ModelHandler, EnvHandler, PersonaHandler,
)
from weclaw.agent.media_processor import process_media
from weclaw.agent.runtime import AgentRuntime
from weclaw.agent.tools import create_timer_job_tool
from weclaw.gateway.protocol import MsgType
from weclaw.utils.agent_config import AgentConfig
from weclaw.utils.job_scheduler import JobScheduler
from weclaw.utils.paths import get_jobs_db_path

logger = logging.getLogger(__name__)


# ── WebSocket MessageTransport ─────────────────────────────────


class WebSocketMessageTransport:
    """WebSocket 消息传输层 - 实现 MessageTransport 协议。

    通过 WebSocket 的 send_and_wait 请求-响应机制处理 message 工具调用。
    """

    def __init__(self, session: "Session") -> None:
        self._session = session

    async def send_message(self, query_params: dict) -> dict:
        """实现 MessageTransport 协议"""
        response = await self._session.send_and_wait(query_params)
        return response


# ── Session ────────────────────────────────────────────────────


class Session:
    """WebSocket 会话：管理 Agent 生命周期、消息路由、流式推送。"""

    def __init__(self, websocket):
        self.websocket = websocket
        self._closed = False
        self.inject_prompt: str = ""
        self.model_name: str | None = None
        self.session_id: str = "main"
        self.config: AgentConfig = AgentConfig(session_id=self.session_id)

        # AgentRuntime（惰性初始化）
        self._runtime: AgentRuntime | None = None
        self._job_scheduler: JobScheduler | None = None

        # WebSocket 基础设施
        self.pending_requests: dict[str, asyncio.Future] = {}
        self._tasks: set[asyncio.Task] = set()
        self._response_queue: asyncio.Queue = asyncio.Queue()
        self._queue_worker_task: asyncio.Task | None = None
        self._queue_closing = False

        # 注册 Handler
        self._handler_map: dict[str, BaseHandler] = {}
        for handler in [
            SkillHandler(websocket),
            ModelHandler(websocket, self),
            EnvHandler(websocket, self),
            PersonaHandler(websocket, self),
        ]:
            for action in handler.ACTIONS:
                self._handler_map[action] = handler

        logger.info(f"新客户端连接: {websocket.remote_address}")
        self._queue_worker_task = asyncio.create_task(self._response_queue_worker())

    @property
    def agent(self):
        """向后兼容：访问底层 Agent 实例。"""
        return self._runtime.agent if self._runtime else None

    async def reset_agent(self) -> None:
        """重置 Agent（ClientContext Protocol 实现）"""
        if self._runtime is not None:
            await self._runtime.close()
            self._runtime = None

    async def initialize_agent(self):
        """惰性初始化 Agent"""
        if self._runtime is not None and self._runtime.agent is not None:
            return

        try:
            # 创建 JobScheduler
            alert_kwargs = {}
            if self.config.job_alert_enabled:
                alert_kwargs = {
                    "on_alert": self._handle_job_alert,
                    "alert_check_interval": self.config.job_alert_check_interval,
                    "alert_ahead_seconds": self.config.job_alert_ahead_seconds,
                }
            self._job_scheduler = JobScheduler(
                db_path=get_jobs_db_path(),
                on_fire=self._handle_job_fire,
                **alert_kwargs,
            )
            await self._job_scheduler.start()

            # 创建 timer_job 工具
            _timer_job_tool = create_timer_job_tool(self._job_scheduler)

            # 使用 AgentRuntime 初始化 Agent
            transport = WebSocketMessageTransport(self)
            self._runtime = AgentRuntime(
                session_id=self.session_id,
                config=self.config,
                message_transport=transport,
                extra_tools=[_timer_job_tool],
            )
            await self._runtime.initialize(
                inject_prompt=self.inject_prompt,
                model_name=self.model_name,
            )
            logger.info("Agent 初始化成功")
        except Exception:
            logger.exception("初始化 Agent 失败")
            raise

    # ── 定时任务回调 ──

    async def _handle_job_alert(self, upcoming_jobs: list[dict]) -> None:
        if self.agent is None:
            return
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"[系统预警] 当前时间: {now_str}", f"以下 {len(upcoming_jobs)} 个定时任务即将到期："]
        for job in upcoming_jobs:
            lines.append(f"- {job['description']} (到期: {job['fire_time']})")
        lines.append("请用简洁友好的方式提醒用户。")
        await self._enqueue_stream_response("\n".join(lines), str(uuid.uuid4()))

    async def _handle_job_fire(self, job_id: str, description: str) -> None:
        if self.agent is None:
            return
        prompt = f"定时任务到期，job_id={job_id}\ndescription={description}"
        await self._enqueue_stream_response(prompt, str(uuid.uuid4()))

    # ── 流式响应 ──

    async def _response_queue_worker(self) -> None:
        while not self._queue_closing:
            try:
                coro = await self._response_queue.get()
                try:
                    await coro
                except Exception as e:
                    logger.exception(f"队列任务异常: {e}")
                finally:
                    self._response_queue.task_done()
            except asyncio.CancelledError:
                break

    async def _enqueue_stream_response(self, prompt, message_id: str) -> None:
        await self._response_queue.put(self._stream_agent_response(prompt, message_id))

    async def _stream_agent_response(self, prompt, message_id: str) -> None:
        if self._runtime is None or self._runtime.agent is None:
            logger.warning("Agent 未初始化，跳过流式响应")
            return
        await self.websocket.send(json.dumps({"id": message_id, "type": MsgType.START}, ensure_ascii=False))
        try:
            async for chunk in self._runtime.agent.astream_text(prompt):
                await self.websocket.send(json.dumps(
                    {"id": message_id, "type": MsgType.CHUNK, "chunk": chunk}, ensure_ascii=False
                ))
        except Exception as e:
            logger.exception(f"流式响应异常: {e}")
            try:
                await self.websocket.send(json.dumps(
                    {"id": message_id, "type": MsgType.ERROR, "error": str(e)}, ensure_ascii=False
                ))
            except Exception:
                pass
        finally:
            await self.websocket.send(json.dumps({"id": message_id, "type": MsgType.END}, ensure_ascii=False))

    # ── WebSocket 消息处理 ──

    async def send_and_wait(self, message, timeout=30.0):
        request_id = str(uuid.uuid4())
        future = asyncio.Future()
        self.pending_requests[request_id] = future
        msg = {**message, "id": request_id, "type": MsgType.TOOL}
        try:
            await self.websocket.send(json.dumps(msg))
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"Timeout for request {request_id}")
            return {"error": "timeout", "message": f"Request timed out after {timeout}s"}
        finally:
            self.pending_requests.pop(request_id, None)

    async def handle_user_message(self, request: dict) -> None:
        await self.initialize_agent()
        message_id = request.get("id", "")
        try:
            prompt = await process_media(request)
            await self._enqueue_stream_response(prompt, message_id)
        except Exception as e:
            logger.exception(f"处理 user 消息异常: {e}")
            await self.websocket.send(json.dumps(
                {"id": message_id, "type": MsgType.ERROR, "error": str(e)}, ensure_ascii=False
            ))

    async def handle_system_message(self, message: dict) -> None:
        action = message.get("action", "")
        handler = self._handler_map.get(action)
        if handler:
            await handler.handle(action, message)
        else:
            logger.warning(f"未知 action: {action}")

    async def handle_tool_message(self, message: dict):
        request_id = message["id"]
        future = self.pending_requests.get(request_id)
        if future and not future.done():
            future.set_result(message)

    async def handle_text_message(self, raw: str) -> None:
        async def _process():
            try:
                request = json.loads(raw)
                msg_type = request.get("type", MsgType.USER)
                if msg_type == MsgType.USER:
                    await self.handle_user_message(request)
                elif msg_type == MsgType.SYSTEM:
                    await self.handle_system_message(request)
                elif msg_type == MsgType.TOOL:
                    await self.handle_tool_message(request)
                else:
                    logger.warning(f"未知消息类型: {msg_type}")
            except json.JSONDecodeError as e:
                await self.websocket.send(json.dumps(
                    {"type": MsgType.ERROR, "error": f"JSON 解析失败: {e}"}, ensure_ascii=False
                ))

        task = asyncio.create_task(_process())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def run(self):
        try:
            async for message in self.websocket:
                if isinstance(message, (bytes, bytearray)):
                    logger.info(f"收到二进制消息，长度: {len(message)}")
                else:
                    await self.handle_text_message(message)
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"客户端断开: {self.websocket.remote_address}")
        finally:
            await self.close()

    async def close(self):
        if self._closed:
            return
        self._closed = True

        for future in self.pending_requests.values():
            if not future.done():
                future.cancel()
        self.pending_requests.clear()

        self._queue_closing = True

        if self._queue_worker_task and not self._queue_worker_task.done():
            self._queue_worker_task.cancel()
            try:
                await self._queue_worker_task
            except asyncio.CancelledError:
                pass

        for task in self._tasks:
            if not task.done():
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        if self._job_scheduler:
            try:
                await self._job_scheduler.stop()
            except Exception:
                pass
            self._job_scheduler = None

        if self._runtime:
            try:
                await self._runtime.close()
            except Exception:
                pass
            self._runtime = None

        try:
            if not self.websocket.closed:
                await self.websocket.close()
        except Exception:
            pass

        logger.info(f"Session 已关闭: {getattr(self.websocket, 'remote_address', None)}")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()
