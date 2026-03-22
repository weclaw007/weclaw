import asyncio
import json
import logging
import uuid
from typing import Dict

import websockets
from langchain_core.tools import BaseTool, tool

from weclaw.agent.agent import Agent
from weclaw.agent.media_processor import process_media
from weclaw.agent.skill_manager import SkillManager
from weclaw.agent.handlers import SkillHandler, ModelHandler, EnvHandler, PersonaHandler, BaseHandler
from weclaw.utils.agent_config import AgentConfig
from weclaw.utils.job_scheduler import JobScheduler
from weclaw.utils.paths import get_jobs_db_path

from datetime import datetime


# module logger
logger = logging.getLogger(__name__)


def build_system_prompt(skill_manager: SkillManager, read_skill_name: str = "read_skill", config: AgentConfig | None = None) -> str:
    """构建包含技能列表和工具结果归档提示的系统提示词。

    这是项目中构建 system prompt 的唯一入口，agent.py 和 client.py 都应复用此函数。
    如果配置了人格设置，会自动注入到提示词开头。

    Args:
        skill_manager: 技能管理器
        read_skill_name: 读取技能的工具名
        config: Agent 配置管理器，传入以避免重复创建
    """
    skills_json = skill_manager.format_as_json()

    # 读取人格配置
    persona = config.persona if config else ""

    prompt_lines = []

    # 如果配置了人格，注入到提示词开头
    if persona:
        prompt_lines.append("## Persona")
        prompt_lines.append(persona)
        prompt_lines.append("")

    prompt_lines += [
        "## Tool Result Archive",
        "In conversation history, some earlier tool call results have been archived.",
        'You will see "[Tool Result Archived] ID: xxx" markers with tool name and args info.',
        "If you need the full result, call the read_tool_result tool with the corresponding ID.",
        "If the current question is unrelated to archived content, no need to read it.",
        "",
        "## Skills (mandatory)",
        "Before replying: scan the available_skills JSON array below.",
        "Skill selection rules:",
        f"- If exactly one skill clearly applies: read its SKILL.md at 'name' with `{read_skill_name}`, then follow it.",
        "- If the user request involves multiple steps that span different skills:",
        "  1. Break the task into sequential sub-steps.",
        "  2. Read the most relevant skill first, execute it.",
        "  3. Then read and execute the next skill as needed.",
        "  4. Continue until all sub-steps are complete.",
        "- If none clearly apply: do not read any SKILL.md.",
        "When a skill file references a relative path, join it with the `location` field (`location` / relative path)",
        "",
        skills_json,
        "",
        "## Task Planning",
        "For complex user requests that may involve multiple tools or skills:",
        "1. **Analyze**: Identify all the sub-tasks needed to fulfill the request.",
        "2. **Plan**: Determine the execution order and dependencies between steps.",
        "3. **Execute**: Carry out each sub-task in sequence, using the appropriate skill/tool.",
        "4. **Summarize**: After all steps complete, give the user a concise summary of what was done.",
        "",
        "Example: User says 'Help me schedule a meeting with Xiao Wang tomorrow at 3pm'",
        "  → Sub-tasks: (1) Create meeting via tencent-meeting skill,",
        "    (2) Set a reminder 15min before via timer_job tool.",
        "",
    ]

    return "\n".join(prompt_lines)

class Client:
    def __init__(self, websocket):
        self.websocket = websocket
        self._closed = False
        self.agent: Agent | None = None
        self.inject_prompt: str = ""
        self.model_name: str | None = None  # 当前使用的模型配置名
        self.session_id: str = "main"  # 会话 ID，每个 agent 独立配置
        self.config: AgentConfig = AgentConfig(session_id=self.session_id)  # 每个 session 独立配置
        self._job_scheduler: JobScheduler | None = None  # 定时任务调度器
        self.pending_requests: Dict[str, asyncio.Future] = {}
        self._tasks: set[asyncio.Task] = set()  # 跟踪所有 create_task 创建的任务
        self._response_queue: asyncio.Queue = asyncio.Queue()  # 串行执行队列
        self._queue_worker_task: asyncio.Task | None = None  # 队列消费协程

        # 注册系统消息处理器（self 实现了 ClientContext Protocol）
        # 使用 action → handler 字典映射，实现 O(1) 精准路由
        self._handler_map: dict[str, BaseHandler] = {}
        for handler in [
            SkillHandler(websocket),
            ModelHandler(websocket, self),
            EnvHandler(websocket, self),
            PersonaHandler(websocket, self),
        ]:
            for action in handler.ACTIONS:
                if action in self._handler_map:
                    logger.warning(
                        f"action '{action}' 已被 {type(self._handler_map[action]).__name__} 注册，"
                        f"将被 {type(handler).__name__} 覆盖"
                    )
                self._handler_map[action] = handler

        logger.info(f"新客户端连接: {websocket.remote_address}")
        # 启动串行队列 worker
        self._queue_worker_task = asyncio.ensure_future(self._response_queue_worker())

    async def reset_agent(self) -> None:
        """重置 Agent：销毁旧实例，下次对话时会用新配置重新初始化。

        此方法是 ClientContext Protocol 的实现，Handler 通过接口调用此方法，
        而非直接操作 self.agent 属性。
        """
        if self.agent is not None:
            await self.agent.close()
            self.agent = None

    async def initialize_agent(self):
        """初始化 Agent"""
        # 避免重复初始化
        if self.agent is not None:
            return

        try:
            # 获取单例 SkillManager
            skill_manager = SkillManager.get_instance()

            # 使用 build_system_prompt 构建系统提示词
            system_prompt = build_system_prompt(skill_manager, config=self.config)
            if self.inject_prompt:
                system_prompt += "\n\n" + self.inject_prompt

            # 内置message tool
            @tool
            async def message(query_params: dict) -> dict:
                """
                处理所有的 channel 信息，比如 wechat-channel
                query_params 参数: json 对象， 每个消息必须有 action 字段
                """
                # 检查query_params是否包含action字段
                if 'action' not in query_params:
                    return {"error": "query_params must contain 'action' field", "result": "error"}

                print(f'message request:\n {query_params} \n')
                response = await self.send_and_wait(query_params)
                print(f'message response:\n {response}\n')
                return response

            # 创建并启动 JobScheduler（定时任务调度器）
            jobs_db = get_jobs_db_path()

            # 读取预警配置
            alert_kwargs = {}
            if self.config.job_alert_enabled:
                alert_kwargs = {
                    "on_alert": self._handle_job_alert,
                    "alert_check_interval": self.config.job_alert_check_interval,
                    "alert_ahead_seconds": self.config.job_alert_ahead_seconds,
                }

            self._job_scheduler = JobScheduler(
                db_path=jobs_db,
                on_fire=self._handle_job_fire,
                **alert_kwargs,
            )
            await self._job_scheduler.start()

            # 创建定时任务工具
            _timer_job_tool = self._create_timer_job_tool()

            # 初始化 Agent
            self.agent = Agent()
            await self.agent.init(
                system_prompt=system_prompt,
                model_name=self.model_name,
                custom_tools=[message, _timer_job_tool],
            )
            logger.info("Agent 初始化成功")
        except Exception as e:
            logger.exception("初始化 Agent 失败")
            raise

    def _create_timer_job_tool(self) -> BaseTool:
        """创建定时任务工具，通过闭包引用 JobScheduler。"""
        scheduler = self._job_scheduler

        def _is_valid_fire_time(fire_time: str) -> bool:
            """校验 fire_time 是否为合法的 ISO 8601 本地时间格式。"""
            from datetime import datetime
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
                try:
                    datetime.strptime(fire_time.split("+")[0].rstrip("Z"), fmt)
                    return True
                except ValueError:
                    continue
            return False

        @tool
        async def timer_job(action: str, params: dict) -> str:
            """定时任务工具，用于创建、更新、删除、查询定时提醒。

            action 可选值及对应 params:
              - add:    {"fire_time": str, "description": str, "repeat_interval": int, "max_repeat": int}  或  {"interval": int, "description": str, "repeat_interval": int, "max_repeat": int}  创建任务，返回 job_id
              - update: {"job_id": str, "fire_time": str, "description": str, "repeat_interval": int, "max_repeat": int}  或  {"job_id": str, "interval": int, "description": str, "repeat_interval": int, "max_repeat": int}  更新任务
              - delete: {"job_id": str}  删除任务
              - query:  {"job_id": str}  查询任务详情
              - list:   {}  列出所有 pending 状态的任务

            触发时间参数（fire_time 和 interval 二选一，不可同时传入）:
              - fire_time: 本地时间的 ISO 8601 格式字符串 YYYY-MM-DDTHH:MM:SS，必须是计算好的绝对时间
                正确示例: "2026-03-19T12:30:00"
                错误示例: "now + 1 minute" / "明天上午8点" / "+1h" （禁止传入相对时间表达式）
              - interval: 从现在起间隔多少秒后首次触发，必须是正整数
                示例: 用户说"1分钟后" → interval=60，用户说"2小时后" → interval=7200
                优先使用 interval，避免因时间计算误差导致 fire_time 不准确

            重复任务参数（可选，不传则为一次性任务）:
              - repeat_interval: 重复间隔秒数，设置后任务将按此间隔重复触发
                示例: 每分钟重复 → repeat_interval=60，每小时重复 → repeat_interval=3600
              - max_repeat: 最大重复次数，不传则无限重复（仅 repeat_interval 有值时生效）
                示例: 重复3次后停止 → max_repeat=3
            """
            logger.info(f"timer_job: {action} {params}")
            if scheduler is None:
                return "定时任务服务未初始化"
            try:
                if action == "add":
                    description = params.get("description")
                    fire_time = params.get("fire_time")
                    interval = params.get("interval")
                    repeat_interval = params.get("repeat_interval")
                    max_repeat = params.get("max_repeat")
                    if not description:
                        return "参数缺失: description"
                    if fire_time and interval:
                        return "fire_time 和 interval 不能同时传入，请二选一"
                    if not fire_time and not interval:
                        return "参数缺失: 必须提供 fire_time 或 interval 其中之一"
                    if interval is not None:
                        from datetime import datetime, timedelta
                        try:
                            interval = int(interval)
                            if interval <= 0:
                                return "interval 必须是正整数（单位：秒）"
                        except (TypeError, ValueError):
                            return f"interval 格式错误: '{interval}'，必须是正整数（单位：秒）"
                    elif not _is_valid_fire_time(fire_time):
                        return (
                            f"fire_time 格式错误: '{fire_time}'。"
                            "必须是本地时间的 ISO 8601 格式，如 '2026-03-19T12:30:00'，"
                            "请先计算出绝对时间再传入，不支持相对时间表达式。"
                        )
                    if repeat_interval is not None:
                        try:
                            repeat_interval = int(repeat_interval)
                            if repeat_interval <= 0:
                                return "repeat_interval 必须是正整数（单位：秒）"
                        except (TypeError, ValueError):
                            return f"repeat_interval 格式错误: '{repeat_interval}'，必须是正整数（单位：秒）"
                    if max_repeat is not None:
                        try:
                            max_repeat = int(max_repeat)
                            if max_repeat <= 0:
                                return "max_repeat 必须是正整数"
                        except (TypeError, ValueError):
                            return f"max_repeat 格式错误: '{max_repeat}'，必须是正整数"
                    job_id = await scheduler.add_job(
                        description=description,
                        fire_time=fire_time,
                        interval=interval,
                        repeat_interval=repeat_interval,
                        max_repeat=max_repeat,
                    )
                    fire_display = fire_time or f"{interval}秒后"
                    repeat_info = f"，每 {repeat_interval} 秒重复" if repeat_interval else ""
                    max_info = f"，最多 {max_repeat} 次" if max_repeat else ("，无限重复" if repeat_interval else "")
                    return f"定时任务已创建，job_id: {job_id}，将于 {fire_display} 触发{repeat_info}{max_info}"
                elif action == "update":
                    job_id = params.get("job_id")
                    description = params.get("description")
                    fire_time = params.get("fire_time")
                    interval = params.get("interval")
                    repeat_interval = params.get("repeat_interval")
                    max_repeat = params.get("max_repeat")
                    if not all([job_id, description]):
                        return "参数缺失: job_id 或 description"
                    if fire_time and interval:
                        return "fire_time 和 interval 不能同时传入，请二选一"
                    if not fire_time and not interval:
                        return "参数缺失: 必须提供 fire_time 或 interval 其中之一"
                    if interval is not None:
                        from datetime import datetime, timedelta
                        try:
                            interval = int(interval)
                            if interval <= 0:
                                return "interval 必须是正整数（单位：秒）"
                        except (TypeError, ValueError):
                            return f"interval 格式错误: '{interval}'，必须是正整数（单位：秒）"
                    elif not _is_valid_fire_time(fire_time):
                        return (
                            f"fire_time 格式错误: '{fire_time}'。"
                            "必须是本地时间的 ISO 8601 格式，如 '2026-03-19T12:30:00'，"
                            "请先计算出绝对时间再传入，不支持相对时间表达式。"
                        )
                    if repeat_interval is not None:
                        try:
                            repeat_interval = int(repeat_interval)
                            if repeat_interval <= 0:
                                return "repeat_interval 必须是正整数（单位：秒）"
                        except (TypeError, ValueError):
                            return f"repeat_interval 格式错误: '{repeat_interval}'，必须是正整数（单位：秒）"
                    if max_repeat is not None:
                        try:
                            max_repeat = int(max_repeat)
                            if max_repeat <= 0:
                                return "max_repeat 必须是正整数"
                        except (TypeError, ValueError):
                            return f"max_repeat 格式错误: '{max_repeat}'，必须是正整数"
                    ok = await scheduler.update_job(
                        job_id=job_id,
                        description=description,
                        fire_time=fire_time,
                        interval=interval,
                        repeat_interval=repeat_interval,
                        max_repeat=max_repeat,
                    )
                    return "更新成功" if ok else "job_id 不存在或已非 pending 状态"
                elif action == "delete":
                    job_id = params.get("job_id")
                    if not job_id:
                        return "参数缺失: job_id"
                    ok = await scheduler.delete_job(job_id)
                    return "删除成功" if ok else "job_id 不存在或已非 pending 状态"
                elif action == "query":
                    job_id = params.get("job_id")
                    if not job_id:
                        return "参数缺失: job_id"
                    job = await scheduler.get_job(job_id)
                    if job is None:
                        return "job_id 不存在"
                    repeat_info = ""
                    if job.get('repeat_interval'):
                        repeat_info = (
                            f"\nrepeat_interval: 每 {job['repeat_interval']} 秒"
                            f"\nmax_repeat: {job['max_repeat'] if job['max_repeat'] else '无限'}"
                            f"\nrepeat_count: 已触发 {job['repeat_count']} 次"
                        )
                    return (
                        f"job_id: {job['job_id']}\n"
                        f"fire_time: {job['fire_time']}\n"
                        f"description: {job['description']}\n"
                        f"status: {job['status']}\n"
                        f"created_at: {job['created_at']}"
                        f"{repeat_info}"
                    )
                elif action == "list":
                    jobs = await scheduler.list_pending_jobs()
                    if not jobs:
                        return "当前没有 pending 状态的定时任务"
                    lines = [f"共 {len(jobs)} 个 pending 任务:"]
                    for j in jobs:
                        repeat_tag = ""
                        if j.get('repeat_interval'):
                            max_r = j['max_repeat']
                            count = j['repeat_count']
                            repeat_tag = f", 每{j['repeat_interval']}s重复"
                            repeat_tag += f"(已触发{count}/{max_r}次)" if max_r else f"(已触发{count}次)"
                        lines.append(
                            f"  - job_id: {j['job_id']}, "
                            f"fire_time: {j['fire_time']}, "
                            f"description: {j['description'][:50]}"
                            f"{repeat_tag}"
                        )
                    return "\n".join(lines)
                else:
                    return "未知 action，支持 add, update, delete, query, list"
            except Exception as e:
                return f"定时任务异常: {e}"

        return timer_job

    # ── 定时任务回调 ──────────────────────────────────────

    async def _handle_job_alert(self, upcoming_jobs: list[dict]) -> None:
        """定时任务预警回调：由 JobScheduler 巡检到即将到期的任务后调用。

        将即将到期的任务信息组装成 prompt，交给大模型生成友好的提醒文案，
        通过 WebSocket 流式推送给前端。
        """
        if self.agent is None:
            logger.warning("定时任务预警回调但 Agent 未初始化")
            return

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        alert_lines = [f"[系统预警] 当前时间: {now_str}"]
        alert_lines.append(f"以下 {len(upcoming_jobs)} 个定时任务即将到期，请提醒用户注意：")
        alert_lines.append("")
        for job in upcoming_jobs:
            alert_lines.append(f"- 任务描述: {job['description']}")
            alert_lines.append(f"  到期时间: {job['fire_time']}")
            alert_lines.append(f"  任务ID: {job['job_id']}")
            alert_lines.append("")
        alert_lines.append("请用简洁友好的方式提醒用户这些即将到期的任务，告知剩余时间。")

        prompt = "\n".join(alert_lines)
        message_id = str(uuid.uuid4())
        logger.info(f"定时任务预警推送: {len(upcoming_jobs)} 个任务即将到期")
        await self._enqueue_stream_response(prompt, message_id)

    async def _response_queue_worker(self) -> None:
        """串行消费响应队列，确保同一时刻只有一个 _stream_agent_response 在执行。"""
        while True:
            try:
                coro = await self._response_queue.get()
                try:
                    await coro
                except Exception as e:
                    logger.exception(f"队列任务执行异常: {e}")
                finally:
                    self._response_queue.task_done()
            except asyncio.CancelledError:
                break

    async def _enqueue_stream_response(self, prompt, message_id: str) -> None:
        """将一次 _stream_agent_response 调用投递到串行队列中排队执行。

        Args:
            prompt: 传给大模型的输入（字符串或 dict）
            message_id: 本次消息的唯一 ID，用于前端关联响应
        """
        await self._response_queue.put(self._stream_agent_response(prompt, message_id))

    async def _stream_agent_response(self, prompt, message_id: str) -> None:
        """调用 agent.astream_text 并将结果以 start/chunk/end 格式流式推送给客户端。

        Args:
            prompt: 传给大模型的输入（字符串或 dict）
            message_id: 本次消息的唯一 ID，用于前端关联响应
        """
        # 发送开始标志
        await self.websocket.send(json.dumps(
            {"id": message_id, "type": "start"}, ensure_ascii=False
        ))
        async for chunk in self.agent.astream_text(prompt):
            await self.websocket.send(json.dumps(
                {"id": message_id, "type": "chunk", "chunk": chunk}, ensure_ascii=False
            ))
        # 发送结束标志
        await self.websocket.send(json.dumps(
            {"id": message_id, "type": "end"}, ensure_ascii=False
        ))

    async def _handle_job_fire(self, job_id: str, description: str) -> None:
        """定时任务到期：将任务描述交给大模型处理，由大模型决定如何响应。"""
        if self.agent is None:
            logger.warning(f"定时任务到期但 Agent 未初始化: job_id={job_id}")
            return

        prompt = f"定时任务到期，job_id={job_id}\ndescription={description}\n"
        message_id = str(uuid.uuid4())
        logger.info(f"定时任务开始处理: {message_id}， {prompt}")
        await self._enqueue_stream_response(prompt, message_id)
        logger.info(f"定时任务已入队: {message_id}")

    async def send_and_wait(self, message, timeout=30.0):
        """
        Send a message to client and wait for response
        """
        # Generate unique request ID
        request_id = str(uuid.uuid4())

        # Create future for this request
        future = asyncio.Future()
        self.pending_requests[request_id] = future

        # Add id to message
        message_with_id = message.copy()
        message_with_id['id'] = request_id
        message_with_id["type"] = "tool"

        try:
            # Send message to client
            await self.websocket.send(json.dumps(message_with_id))
            print(f"Sent message to client with id: {request_id}")

            # Wait for response with timeout
            response = await asyncio.wait_for(future, timeout=timeout)
            return response

        except asyncio.TimeoutError:
            print(f"Timeout waiting for response from client for id: {request_id}")
        finally:
            # Clean up pending request
            if request_id in self.pending_requests:
                del self.pending_requests[request_id]

    async def handle_binary_message(self, message: bytes) -> None:
        logger.info(f"收到二进制消息，长度: {len(message)}")

    async def handle_user_message(self, request: dict) -> None:
        """处理文本消息（JSON格式）
        
        消息格式:
        {
            "id": "unique-message-id",
            "type": "user",
            "text": "描述这些内容",
            "image": [
                {"type": "file", "data": "/path/1.jpg"},
                {"type": "url", "data": "https://..."}
            ],
            "audio": [
                {"type": "file", "data": "/path/audio.wav"},
                {"type": "base64", "data": "...", "mime": "audio/wav"}
            ],
            "video": [
                {"type": "url", "data": "https://...mp4"}
            ]
        }
        
        媒体项 type 支持: "file"（本地文件路径）、"url"（URL链接）、"base64"（Base64编码数据）
        
        响应格式:
        开始: {"id": "unique-message-id", "type": "start"}
        流式: {"id": "unique-message-id", "type": "chunk", "chunk": "响应文本片段"}
        结束: {"id": "unique-message-id", "type": "end"}
        错误: {"id": "unique-message-id", "type": "error", "error": "错误信息"}
 
        Args:
            request: 解析后的 JSON 消息对象，包含 id 和其他字段
        """
        await self.initialize_agent()
        message_id = request.get("id", "")
        try:
            logger.info(f"处理 user 消息 [{message_id}]: {request}")

            # 媒体预处理：将音频/图片/视频通过多模态模型转为纯文本
            prompt = await process_media(request)

            # 使用 agent 处理并流式返回结果（入队串行执行）
            await self._enqueue_stream_response(prompt, message_id)
            logger.info(f"user 消息已入队 [{message_id}]")

        except Exception as e:
            logger.exception(f"处理 user 消息时发生异常: {e}")
            error_response = json.dumps({"id": message_id, "type": "error", "error": str(e)}, ensure_ascii=False)
            await self.websocket.send(error_response)

    async def handle_system_message(self, message: dict) -> None:
        """路由系统消息到对应的 Handler（基于字典精准路由）"""
        action = message.get("action", "")
        handler = self._handler_map.get(action)
        if handler is not None:
            await handler.handle(action, message)
        else:
            logger.warning(f"未找到处理 action='{action}' 的 Handler")

    async def handle_tool_message(self, message: dict):
        request_id = message['id']
        if request_id in self.pending_requests:
            future = self.pending_requests[request_id]
            if not future.done():
                future.set_result(message)
                print(f"Completed request with id: {request_id}")
        print(f"Handled response for id: {request_id}")

    async def handle_text_message(self, message: str) -> None:
        async def process_message_async():
            message_id = ""
            try:
                # 解析 JSON 字符串
                request = json.loads(message)
                message_id = request.get("id", "")
                msg_type = request.get("type", "user")  # 默认为 user 类型

                logger.info(f"收到消息 [{message_id}], 类型: {msg_type}")

                # 根据消息类型分别处理
                if msg_type == "user":
                    await self.handle_user_message(request)
                elif msg_type == "system":
                    await self.handle_system_message(request)
                elif msg_type == "tool":
                    await self.handle_tool_message(request)
                else:
                    # 未知的消息类型
                    logger.warning(f"收到未知类型的消息 [{message_id}], 类型: {msg_type}")

            except json.JSONDecodeError as e:
                logger.error(f"JSON 解析失败: {e}, 原始消息: {message}")
                error_response = json.dumps(
                    {"id": message_id, "type": "error", "error": f"无效的 JSON 格式 - {str(e)}"}, ensure_ascii=False)
                await self.websocket.send(error_response)

        task = asyncio.create_task(process_message_async())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def run(self):
        """运行客户端消息循环"""
        # 初始化代理
        try:
            async for message in self.websocket:
                if isinstance(message, (bytes, bytearray)):
                    await self.handle_binary_message(message)
                else:
                    await self.handle_text_message(message)
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"客户端断开连接: {self.websocket.remote_address}")
        finally:
            await self.close()

    async def close(self):
        """关闭 websocket 和 agent 资源（幂等）。"""
        if self._closed:
            return
        self._closed = True

        # 取消所有待处理的请求 Future，防止协程永远挂起
        for req_id, future in self.pending_requests.items():
            if not future.done():
                future.cancel()
        self.pending_requests.clear()

        # 取消队列 worker
        if self._queue_worker_task and not self._queue_worker_task.done():
            self._queue_worker_task.cancel()
            try:
                await self._queue_worker_task
            except asyncio.CancelledError:
                pass
            self._queue_worker_task = None

        # 取消所有正在运行的任务
        for task in self._tasks:
            if not task.done():
                task.cancel()
        # 等待所有任务完成取消
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        # 关闭 JobScheduler
        try:
            if self._job_scheduler is not None:
                await self._job_scheduler.stop()
                self._job_scheduler = None
        except Exception:
            pass

        try:
            if self.agent is not None:
                await self.agent.close()
                self.agent = None  # 断开循环引用（message 闭包 → Client → Agent）
        except Exception:
            pass
        try:
            if not self.websocket.closed:
                await self.websocket.close()
        except Exception:
            pass
        logger.info(f"Client 已关闭: {getattr(self.websocket, 'remote_address', None)}")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()
