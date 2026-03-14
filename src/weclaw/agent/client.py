import asyncio
import json
import logging
import os
import uuid
from typing import Dict

import websockets
from langchain_core.tools import tool

from weclaw.agent.agent import Agent
from weclaw.agent.skill_manager import SkillManager


# module logger
logger = logging.getLogger(__name__)


def build_system_prompt(skill_manager: SkillManager, read_skill_name: str = "read_skill") -> str:
    """构建包含技能列表的系统提示词。"""
    skills_json = skill_manager.format_as_json()

    prompt_lines = [
        "## Skills (mandatory)",
        "Before replying: scan the available_skills JSON array below.",
        f"- If exactly one skill clearly applies: read its SKILL.md at 'name' with `{read_skill_name}`, then follow it.",
        "- If multiple could apply: choose the most specific one, then read/follow it.",
        "- If none clearly apply: do not read any SKILL.md.",
        "Constraints: never read more than one skill up front; only read after selecting.",
        "When a skill file references a relative path, join it with the `location` field (`location` / relative path)",
        "",
        skills_json,
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
        self.pending_requests: Dict[str, asyncio.Future] = {}
        self._tasks: set[asyncio.Task] = set()  # 跟踪所有 create_task 创建的任务
        logger.info(f"新客户端连接: {websocket.remote_address}")

    async def initialize_agent(self):
        """初始化 Agent"""
        # 避免重复初始化
        if self.agent is not None:
            return

        try:
            # 获取单例 SkillManager
            skill_manager = SkillManager.get_instance()

            # 使用 build_system_prompt 构建系统提示词
            system_prompt = build_system_prompt(skill_manager)
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

            # 初始化 Agent
            self.agent = Agent()
            await self.agent.init(
                system_prompt=system_prompt,
                model_name=self.model_name,
                custom_tools=[message],
            )
            logger.info("Agent 初始化成功")
        except Exception as e:
            logger.exception("初始化 Agent 失败")
            raise

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
        await self.initialize_agent()
        """处理文本消息（JSON格式）
        
        消息格式:
        {
            "id": "unique-message-id",
            "type": "user",
            "text": "abc",
            "image": "/path/to/image.png",
            "audio": "/path/to/audio.wav",
            "video": "/path/to/video.mp4"
        }
        
        响应格式:
        开始: {"id": "unique-message-id", "type": "start"}
        流式: {"id": "unique-message-id", "type": "chunk", "chunk": "响应文本片段"}
        结束: {"id": "unique-message-id", "type": "end"}
        错误: {"id": "unique-message-id", "type": "error", "error": "错误信息"}
 
        Args:
            request: 解析后的 JSON 消息对象，包含 id 和其他字段
        """
        message_id = request.get("id", "")
        try:
            logger.info(f"处理 user 消息 [{message_id}]: {request}")

            # 发送开始标志
            start_response = json.dumps({"id": message_id, "type": "start"}, ensure_ascii=False)
            await self.websocket.send(start_response)

            # 使用 agent 处理并流式返回结果
            async for chunk in self.agent.astream_text(request):
                response = json.dumps({"id": message_id, "type": "chunk", "chunk": chunk}, ensure_ascii=False)
                await self.websocket.send(response)

            # 发送结束标志
            end_response = json.dumps({"id": message_id, "type": "end"}, ensure_ascii=False)
            await self.websocket.send(end_response)

        except Exception as e:
            logger.exception(f"处理 user 消息时发生异常: {e}")
            error_response = json.dumps({"id": message_id, "type": "error", "error": str(e)}, ensure_ascii=False)
            await self.websocket.send(error_response)

    async def handle_prompt_message(self, message: dict) -> None:
        """处理系统消息（prompt）"""
        prompt = message.get("text", "")
        logger.info(f"处理 prompt 消息: {prompt}")
        self.inject_prompt = prompt

    async def handle_get_skills_message(self, message: dict) -> None:
        """处理获取技能列表消息"""
        # 获取单例 SkillManager
        skill_manager = SkillManager.get_instance()
        '''
         ["name": "文件处理器",
                "emoji": "📄",
                "description": "自动处理各种文件格式，支持PDF、Word、Excel等文档转换",
                "primaryEnv": "DASHSCOPE_API_KEY",
                "enabled": False
            }]
        '''
        skills = skill_manager.get_skills_for_current_os()
        skills_json = []
        for skill, value in skills.items():
            env_name = value.get("metadata", {}).get("openclaw", {}).get("primaryEnv", "")
            skill_json = {"name": value["name"], "description": value["description"],
                          "emoji": value.get("metadata", {}).get("openclaw", {}).get("emoji", ""),
                          "primaryEnv": os.getenv(env_name) if env_name else "",
                          "envName": env_name,
                          "enabled": skill_manager.is_skill_enabled(skill),
                          "builtin": value.get("_builtin", True)}

            skills_json.append(skill_json)
        # 发送技能列表到客户端
        message_id = message.get("id", "")
        response = json.dumps({"id": message_id, "type": "system", "skills": skills_json, "action":"get_skills"}, ensure_ascii=False)
        await self.websocket.send(response)

    async def handle_enable_skill_message(self, message: dict) -> None:
        """处理启用技能消息"""
        skill_name = message.get("skill_name", "")
        message_id = message.get("id", "")
        skill_manager = SkillManager.get_instance()

        try:
            success = skill_manager.enable_skill(skill_name)
            response = json.dumps({
                "id": message_id, "type": "system",
                "action": "enable_skill",
                "skill_name": skill_name,
                "success": success
            }, ensure_ascii=False)
        except Exception as e:
            logger.exception(f"启用技能 '{skill_name}' 失败")
            response = json.dumps({
                "id": message_id, "type": "system",
                "action": "enable_skill",
                "skill_name": skill_name,
                "success": False,
                "error": str(e)
            }, ensure_ascii=False)
        await self.websocket.send(response)

    async def handle_disable_skill_message(self, message: dict) -> None:
        """处理禁用技能消息"""
        skill_name = message.get("skill_name", "")
        message_id = message.get("id", "")
        skill_manager = SkillManager.get_instance()

        try:
            success = skill_manager.disable_skill(skill_name)
            response = json.dumps({
                "id": message_id, "type": "system",
                "action": "disable_skill",
                "skill_name": skill_name,
                "success": success
            }, ensure_ascii=False)
        except Exception as e:
            logger.exception(f"禁用技能 '{skill_name}' 失败")
            response = json.dumps({
                "id": message_id, "type": "system",
                "action": "disable_skill",
                "skill_name": skill_name,
                "success": False,
                "error": str(e)
            }, ensure_ascii=False)
        await self.websocket.send(response)

    @staticmethod
    def _find_env_file() -> str:
        """查找 .env 文件路径，使用 dotenv 的 find_dotenv 定位"""
        try:
            from dotenv import find_dotenv
            env_path = find_dotenv(usecwd=True)
            if env_path:
                return env_path
        except ImportError:
            pass
        # 回退：从当前文件向上查找包含 .env 的目录
        from pathlib import Path
        current = Path(__file__).resolve().parent
        for _ in range(10):
            candidate = current / ".env"
            if candidate.exists():
                return str(candidate)
            parent = current.parent
            if parent == current:
                break
            current = parent
        # 如果找不到，默认在项目根目录创建
        return str(Path(__file__).resolve().parent.parent.parent.parent / ".env")

    @staticmethod
    def _save_env_to_file(env_path: str, env_name: str, api_key: str) -> None:
        """将环境变量写入 .env 文件（更新已有的或追加新的）"""
        from pathlib import Path
        env_file = Path(env_path)
        lines = []
        found = False

        if env_file.exists():
            with open(env_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # 查找并替换已有的同名变量
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith(f"{env_name}=") or stripped.startswith(f"{env_name} ="):
                    lines[i] = f"{env_name}={api_key}\n"
                    found = True
                    break

        if not found:
            # 追加新的环境变量
            if lines and not lines[-1].endswith("\n"):
                lines.append("\n")
            lines.append(f"{env_name}={api_key}\n")

        with open(env_file, "w", encoding="utf-8") as f:
            f.writelines(lines)

    async def handle_save_api_key_message(self, message: dict) -> None:
        """处理保存 API Key 消息，同时写入内存环境变量和 .env 文件"""
        skill_name = message.get("skill_name", "")
        env_name = message.get("env_name", "")
        api_key = message.get("api_key", "")
        message_id = message.get("id", "")

        try:
            if env_name and api_key:
                # 1. 设置内存中的环境变量（立即生效）
                os.environ[env_name] = api_key
                # 2. 持久化写入 .env 文件（重启后仍生效）
                env_path = self._find_env_file()
                self._save_env_to_file(env_path, env_name, api_key)
                logger.info(f"已保存 API Key: 技能={skill_name}, 环境变量={env_name}, 文件={env_path}")
                response = json.dumps({
                    "id": message_id, "type": "system",
                    "action": "save_api_key",
                    "skill_name": skill_name,
                    "success": True
                }, ensure_ascii=False)
            else:
                response = json.dumps({
                    "id": message_id, "type": "system",
                    "action": "save_api_key",
                    "skill_name": skill_name,
                    "success": False,
                    "error": "环境变量名或 API Key 为空"
                }, ensure_ascii=False)
        except Exception as e:
            logger.exception(f"保存 API Key 失败: 技能={skill_name}")
            response = json.dumps({
                "id": message_id, "type": "system",
                "action": "save_api_key",
                "skill_name": skill_name,
                "success": False,
                "error": str(e)
            }, ensure_ascii=False)
        await self.websocket.send(response)

    async def handle_switch_model_message(self, message: dict) -> None:
        """处理切换模型消息：销毁旧 Agent，下次对话时用新模型重新初始化"""
        model_name = message.get("model_name", "")
        message_id = message.get("id", "")

        try:
            self.model_name = model_name if model_name else None
            # 关闭旧 Agent，下次 handle_user_message 时会重新初始化
            if self.agent is not None:
                await self.agent.close()
                self.agent = None

            logger.info(f"模型已切换为: {model_name or '默认'}")
            response = json.dumps({
                "id": message_id, "type": "system",
                "action": "switch_model",
                "model_name": model_name,
                "success": True,
            }, ensure_ascii=False)
        except Exception as e:
            logger.exception(f"切换模型失败: {e}")
            response = json.dumps({
                "id": message_id, "type": "system",
                "action": "switch_model",
                "success": False,
                "error": str(e),
            }, ensure_ascii=False)
        await self.websocket.send(response)

    async def handle_get_models_message(self, message: dict) -> None:
        """处理获取可用模型列表消息"""
        from weclaw.utils.model_registry import ModelRegistry

        message_id = message.get("id", "")
        try:
            registry = ModelRegistry.get_instance()
            models = registry.list_available()
            default_model = registry.get_default()
            current_model = self.model_name or default_model

            response = json.dumps({
                "id": message_id, "type": "system",
                "action": "get_models",
                "models": models,
                "default": default_model,
                "current": current_model,
            }, ensure_ascii=False)
        except Exception as e:
            logger.exception(f"获取模型列表失败: {e}")
            response = json.dumps({
                "id": message_id, "type": "system",
                "action": "get_models",
                "models": [],
                "error": str(e),
            }, ensure_ascii=False)
        await self.websocket.send(response)

    async def handle_system_message(self, message: dict) -> None:
        action = message.get("action", "")
        match action:
            case "prompt":
                await self.handle_prompt_message(message)
            # 获取skill 列表
            case "get_skills":
                await self.handle_get_skills_message(message)
            case "enable_skill":
                await self.handle_enable_skill_message(message)
            case "disable_skill":
                await self.handle_disable_skill_message(message)
            case "save_api_key":
                await self.handle_save_api_key_message(message)
            case "switch_model":
                await self.handle_switch_model_message(message)
            case "get_models":
                await self.handle_get_models_message(message)
            case _:
                pass

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

        # 取消所有正在运行的任务
        for task in self._tasks:
            if not task.done():
                task.cancel()
        # 等待所有任务完成取消
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

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
