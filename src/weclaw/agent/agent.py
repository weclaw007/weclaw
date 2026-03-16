import asyncio
import base64
import concurrent.futures
import logging
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Union

import aiosqlite
from langchain.agents import create_agent
from langchain_core.messages import AIMessageChunk
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from weclaw.agent.skill_manager import SkillManager
from weclaw.utils.context_optimizer import (
    archive_tool_result,
    read_archived_tool_result,
    is_archived_tool_message,
    TOOL_ARCHIVE_MIN_LENGTH,
    TOOL_ARCHIVE_PREFIX,
)
from weclaw.utils.model_registry import ModelRegistry
from weclaw.utils.paths import get_checkpoint_db_path

logger = logging.getLogger(__name__)


def base64_encode(path: str | Path) -> str:
    """读取文件并返回 base64 文本。"""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def get_mime_type(path: str | Path) -> str:
    """根据扩展名推断 MIME 类型。"""
    ext = Path(path).suffix.lower().lstrip(".")
    if ext in ("jpg", "jpeg"):
        return "image/jpeg"
    if ext == "png":
        return "image/png"
    if ext == "gif":
        return "image/gif"
    if ext == "bmp":
        return "image/bmp"
    if ext == "wav":
        return "audio/wav"
    if ext == "mp3":
        return "audio/mpeg"
    if ext == "mp4":
        return "video/mp4"
    return "application/octet-stream"


# 命令执行使用进程池，避免阻塞主事件循环。
COMMAND_PROCESS_POOL = concurrent.futures.ProcessPoolExecutor(
    max_workers=max(2, (os.cpu_count() or 2) // 2)
)


def _run_command_in_process(command: str, timeout: int) -> dict[str, Any]:
    """在子进程中执行命令并返回结构化结果。"""
    try:
        if os.name == "nt":
            shell_cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
        else:
            shell_cmd = ["bash", "-lc", command]

        completed = subprocess.run(
            shell_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout or "",
            "stderr": completed.stderr or "",
        }
    except subprocess.TimeoutExpired:
        return {"timeout": True}
    except Exception as e:
        return {"error": str(e)}

@tool
async def read_skill(name: str) -> str:
    """读取技能文档内容，参数为技能名称（如 'sqlite', 'websearch'）。"""
    skill_manager = SkillManager.get_instance()

    # 从缓存中查找技能
    if not skill_manager.has_skill(name):
        return f"技能 '{name}' 不存在。可用技能: {', '.join(skill_manager.get_skill_names())}"

    skill_data = skill_manager.get_skill_metadata(name)
    body = skill_data.get("_body", "")

    if not body:
        return f"技能 '{name}' 没有文档内容"

    return body

@tool
async def read_local_file(file_path: str) -> str:
    """读取本地 UTF-8 文本文件。"""
    try:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            return f"文件不存在: {path}"
        if not path.is_file():
            return f"路径不是文件: {path}"

        return await asyncio.to_thread(path.read_text, encoding="utf-8")
    except UnicodeDecodeError:
        return "文件不是 UTF-8 文本，暂不支持读取。"
    except Exception as e:
        return f"读取失败: {e}"


@tool
async def run_command(command: str, timeout: int = 60) -> str:
    """执行命令行工具（Windows: powershell，其他: bash）。"""
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            COMMAND_PROCESS_POOL,
            _run_command_in_process,
            command,
            timeout,
        )

        if result.get("timeout"):
            return f"命令执行超时（{timeout}s）"
        if result.get("error"):
            return f"命令执行异常: {result['error']}"

        stdout = str(result.get("stdout", "")).strip()
        stderr = str(result.get("stderr", "")).strip()
        returncode = int(result.get("returncode", 1))

        if returncode == 0:
            return stdout or "命令执行成功（无输出）"

        details = stderr or stdout or "无错误输出"
        return f"命令执行失败(code={returncode})\n{details}"
    except Exception as e:
        return f"命令执行异常: {e}"



class Agent:
    """封装模型初始化、工具注册与多模态流式推理。"""

    def __init__(self, stream_mode: str = "messages") -> None:
        self.stream_mode = stream_mode
        self.agent: Any | None = None
        self.config: Dict[str, Any] | None = None
        self._db_conn: aiosqlite.Connection | None = None
        self._session_id: str = "main"

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    def __del__(self):
        if self._db_conn is not None:
            logger.warning("Agent 对象被销毁但 SQLite 连接未关闭，请确保调用 await agent.close()")

    async def init(
        self,
        system_prompt: str,
        model_name: str | None = None,
        custom_tools: list[BaseTool] | None = None,
        request_timeout: int = 120,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        """初始化底层模型与 agent。

        Args:
            system_prompt: 系统提示词
            model_name: 模型配置名（对应 models.yaml 中的 key），为 None 时使用默认模型
            custom_tools: 自定义工具列表
            request_timeout: 请求超时时间（秒）
            session_id: 会话 ID，用于持久化检查点
        """
        # 如果已有旧连接，先关闭防止泄漏
        if self._db_conn is not None:
            await self._db_conn.close()
            self._db_conn = None

        # 通过 ModelRegistry 创建 LLM 实例
        registry = ModelRegistry.get_instance()
        llm = registry.create_chat_model(
            name=model_name,
            request_timeout=request_timeout,
            stream_usage=True,
        )

        # session_id 默认为 "main"，每个 session 独立目录
        resolved_session_id = session_id or "main"
        self._session_id = resolved_session_id

        # 使用 SQLite 持久化对话检查点（按 session 隔离）
        db_path = get_checkpoint_db_path(resolved_session_id)
        self._db_conn = await aiosqlite.connect(db_path)
        checkpoint = AsyncSqliteSaver(self._db_conn)
        await checkpoint.setup()  # 初始化数据库表结构
        self.config = {"configurable": {"thread_id": resolved_session_id}}

        # 创建 read_tool_result 工具（闭包捕获 session_id）
        _read_tool_result = self._create_read_tool_result_tool(resolved_session_id)

        # 默认注入系统工具，支持调用方追加自定义工具。
        tools = [run_command, read_local_file, read_skill, _read_tool_result, *(custom_tools or [])]
        self.agent = create_agent(
            model=llm,
            checkpointer=checkpoint,
            system_prompt=system_prompt,
            tools=tools,
        )

    @staticmethod
    def _create_read_tool_result_tool(session_id: str) -> BaseTool:
        """创建 read_tool_result 工具，通过闭包绑定 session_id。"""

        @tool
        async def read_tool_result(tool_call_id: str) -> str:
            """Read the original content of an archived tool call result.

            When you see "[Tool Result Archived] ID: xxx" in conversation history,
            use this tool with the corresponding ID to retrieve the full original result.
            """
            return read_archived_tool_result(session_id, tool_call_id)

        return read_tool_result

    async def close(self) -> None:
        """关闭 SQLite 连接，释放资源。"""
        if self._db_conn is not None:
            await self._db_conn.close()
            self._db_conn = None
            logger.info("SQLite checkpoint 连接已关闭")

    # 工具结果归档：跳过最近 N 轮的 ToolMessage，只归档更早的
    _ARCHIVE_SKIP_RECENT_ROUNDS = 1

    async def _archive_tool_results(self) -> None:
        """扫描对话历史，将超长的 ToolMessage 内容归档到本地文件并替换为摘要。

        只处理非最近 N 轮的 ToolMessage，最近轮次保持原样以确保 LLM 正常推理。
        """
        if self.agent is None or self.config is None:
            return

        try:
            from langchain_core.messages import ToolMessage
            from weclaw.utils.context_optimizer import split_into_rounds

            state = await self.agent.aget_state(self.config)
            messages = state.values.get("messages", [])

            if not messages:
                return

            # 按轮次切分，确定需要保护的最近 N 轮消息 ID 集合
            rounds = split_into_rounds(messages)
            # 过滤掉 SystemMessage 轮次，只统计对话轮次
            from langchain_core.messages import SystemMessage as _SM
            dialog_rounds = [r for r in rounds if not (len(r) == 1 and isinstance(r[0], _SM))]

            # 最近 N 轮的消息 ID 集合（这些不归档）
            protected_ids: set[str] = set()
            for r in dialog_rounds[-self._ARCHIVE_SKIP_RECENT_ROUNDS:]:
                for msg in r:
                    protected_ids.add(msg.id)

            # 构建 tool_call_id -> (tool_name, tool_args) 的映射
            # 从 AIMessage 的 tool_calls 中提取
            tool_call_info: dict[str, tuple[str, str]] = {}
            for msg in messages:
                if msg.type == "ai" and hasattr(msg, "tool_calls"):
                    for tc in (msg.tool_calls or []):
                        tc_id = tc.get("id", "")
                        tc_name = tc.get("name", "unknown")
                        tc_args = str(tc.get("args", {}))[:200]  # 参数摘要，限制长度
                        tool_call_info[tc_id] = (tc_name, tc_args)

            updates = []
            for msg in messages:
                if msg.type != "tool":
                    continue
                # 跳过受保护的最近轮次
                if msg.id in protected_ids:
                    continue
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                # 跳过已归档的、太短的
                if is_archived_tool_message(content):
                    continue
                if len(content) < TOOL_ARCHIVE_MIN_LENGTH:
                    continue

                # 获取工具名称和参数信息
                tc_id = getattr(msg, "tool_call_id", "") or msg.id
                tool_name, tool_args = tool_call_info.get(tc_id, ("unknown", "{}"))

                # 归档到本地文件并生成替换文本
                replacement = archive_tool_result(
                    session_id=self._session_id,
                    tool_call_id=tc_id,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    content=content,
                )

                trimmed = ToolMessage(
                    content=replacement,
                    tool_call_id=msg.tool_call_id,
                    id=msg.id,
                )
                updates.append(trimmed)

            if updates:
                await self.agent.aupdate_state(self.config, {"messages": updates})
                logger.info(f"Archived {len(updates)} ToolMessage(s) (protected recent {self._ARCHIVE_SKIP_RECENT_ROUNDS} round(s))")
        except Exception as e:
            logger.warning(f"归档 ToolMessage 失败: {e}")

    def _build_content(self, input_content: Union[str, Dict[str, Any]]) -> list[dict[str, Any]]:
        """将文本/多模态输入转换为模型所需 content 结构。

        支持两种方式传入多模态数据：
        1. 本地文件路径：image/audio/video 字段，值为文件路径
        2. Base64 编码数据：image_b64/audio_b64/video_b64 字段，值为 base64 字符串
           - 使用 b64 字段时，可通过 image_mime/audio_format/video_mime 指定格式
        """
        if isinstance(input_content, str):
            return [{"type": "text", "text": input_content}]

        content: list[dict[str, Any]] = [{"type": "text", "text": input_content.get("text", "")}]

        # --- 图片处理 ---
        image_b64 = input_content.get("image_b64")
        image_path = input_content.get("image")
        if image_b64:
            # 直接使用 base64 数据，默认 MIME 为 image/png
            try:
                mime = input_content.get("image_mime", "image/png")
                data_uri = f"data:{mime};base64,{image_b64}"
                content.append({"type": "image_url", "image_url": {"url": data_uri}})
            except Exception as e:
                logger.exception(f"处理图片 base64 数据失败: {e}")
        elif image_path and Path(image_path).exists():
            try:
                data_uri = f"data:{get_mime_type(image_path)};base64,{base64_encode(image_path)}"
                content.append({"type": "image_url", "image_url": {"url": data_uri}})
            except Exception as e:
                logger.exception(f"处理图片失败: {e}")

        # --- 音频处理 ---
        audio_b64 = input_content.get("audio_b64")
        audio_path = input_content.get("audio")
        if audio_b64:
            # 直接使用 base64 数据，默认格式为 wav
            try:
                audio_format = input_content.get("audio_format", "wav")
                data_uri = f"data:;base64,{audio_b64}"
                content.append({
                    "type": "input_audio",
                    "input_audio": {"data": data_uri, "format": audio_format},
                })
            except Exception as e:
                logger.exception(f"处理音频 base64 数据失败: {e}")
        elif audio_path and Path(audio_path).exists():
            try:
                data_uri = f"data:;base64,{base64_encode(audio_path)}"
                audio_format = Path(audio_path).suffix.lower().lstrip(".") or "mp3"
                content.append({
                    "type": "input_audio",
                    "input_audio": {"data": data_uri, "format": audio_format},
                })
            except Exception as e:
                logger.exception(f"处理音频失败: {e}")

        # --- 视频处理 ---
        video_b64 = input_content.get("video_b64")
        video_path = input_content.get("video")
        if video_b64:
            # 直接使用 base64 数据，默认 MIME 为 video/mp4
            try:
                mime = input_content.get("video_mime", "video/mp4")
                data_uri = f"data:{mime};base64,{video_b64}"
                content.append({"type": "video_url", "video_url": {"url": data_uri}})
            except Exception as e:
                logger.exception(f"处理视频 base64 数据失败: {e}")
        elif video_path and Path(video_path).exists():
            try:
                data_uri = f"data:;base64,{base64_encode(video_path)}"
                content.append({"type": "video_url", "video_url": {"url": data_uri}})
            except Exception as e:
                logger.exception(f"处理视频失败: {e}")

        return content

    async def astream_text(
        self,
        content: Union[str, Dict[str, Any]],
        context: Any = None,
    ) -> AsyncIterator[str]:
        """只输出文本分片，适用于终端流式打印。"""
        # 记录每次 LLM 调用的 token 用量（一个 agent 轮次可能触发多次 LLM 调用）
        llm_calls: list[dict[str, int]] = []
        current_input = 0
        current_output = 0
        async for message in self.astream(content, context):
            if isinstance(message, tuple) and len(message) > 0:
                chunk = message[0]
                if isinstance(chunk, AIMessageChunk):
                    # usage_metadata 仅在每次 LLM 调用的最后一个 chunk 中返回
                    usage = getattr(chunk, "usage_metadata", None)
                    if usage:
                        cur_in = usage.get("input_tokens", 0)
                        cur_out = usage.get("output_tokens", 0)
                        if cur_in or cur_out:
                            llm_calls.append({"input_tokens": cur_in, "output_tokens": cur_out})
                            current_input += cur_in
                            current_output += cur_out
                    text = getattr(chunk, "content", "")
                    if isinstance(text, str) and text:
                        yield text
        # 流结束后打印 token 用量
        if llm_calls:
            if len(llm_calls) > 1:
                for i, call in enumerate(llm_calls, 1):
                    logger.info(
                        f"  第 {i} 次 LLM 调用 - 输入: {call['input_tokens']}, "
                        f"输出: {call['output_tokens']}, "
                        f"小计: {call['input_tokens'] + call['output_tokens']}"
                    )
            logger.info(
                f"Token 用量汇总 - 输入: {current_input}, 输出: {current_output}, "
                f"合计: {current_input + current_output} (共 {len(llm_calls)} 次 LLM 调用)"
            )

        # 流结束后自动清理上下文
        await self._archive_tool_results()

    async def astream(
        self,
        input_content: Union[str, Dict[str, Any]],
        context: Any = None,
    ) -> AsyncIterator[Any]:
        """输出底层原始流事件，支持文本/图像/音频/视频输入。"""
        if self.agent is None or self.config is None:
            raise RuntimeError("Agent 尚未初始化，请先调用 await init(...)")

        content = self._build_content(input_content)

        try:
            async for chunk in self.agent.astream(
                {"messages": [{"role": "user", "content": content}]},
                stream_mode=self.stream_mode,
                config=self.config,
                context=context,
            ):
                yield chunk
        except Exception as e:
            logger.exception(f"Error while streaming from agent: {e}")
            return

async def main():
    """测试用例：创建 Agent，支持控制台多轮会话"""
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv(usecwd=True))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


    from weclaw.agent.skill_manager import SkillManager
    skills_dir = Path(__file__).resolve().parent.parent / "skills"
    skill_manager = SkillManager.get_instance(skills_dir)
    await skill_manager.load()

    skills_json = skill_manager.format_as_json()

    prompt_lines = [
        "## Tool Result Archive",
        "In conversation history, some earlier tool call results have been archived.",
        "You will see \"[Tool Result Archived] ID: xxx\" markers with tool name and args info.",
        "If you need the full result, call the read_tool_result tool with the corresponding ID.",
        "If the current question is unrelated to archived content, no need to read it.",
        "",
        "## Skills (mandatory)",
        "Before replying: scan the available_skills JSON array below.",
        f"- If exactly one skill clearly applies: read its SKILL.md at 'name' with `read_skill`, then follow it.",
        "- If multiple could apply: choose the most specific one, then read/follow it.",
        "- If none clearly apply: do not read any SKILL.md.",
        "Constraints: never read more than one skill up front; only read after selecting.",
        "When a skill file references a relative path, join it with the `location` field (`location` / relative path)",
        "",
        skills_json,
        "",
    ]

    system_prompt = "\n".join(prompt_lines)

    async with Agent() as agent:
        #await agent.init(system_prompt=system_prompt, model_name="ollama/qwen3.5:9b", request_timeout=10000)
        await agent.init(system_prompt=system_prompt, model_name="qwen-vl", request_timeout=10000)
        print("=" * 50)
        print("多轮对话测试（输入 exit/quit 退出，Ctrl+C 中断）")
        print("=" * 50)

        while True:
            try:
                user_input = input("\n用户: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n再见！")
                break

            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                print("再见！")
                break

            print("助手: ", end="", flush=True)
            async for chunk in agent.astream_text(user_input):
                print(chunk, end="", flush=True)
            print()  # 输出结束换行


if __name__ == "__main__":
    asyncio.run(main())