import gradio as gr
import asyncio
import json
import logging
import os
import time
import uuid

import websockets


def _patch_uvicorn_for_debug():
    """修补 uvicorn.Server.run，解决调试模式下事件循环冲突的问题。
    调试器（如 debugpy）可能在子线程中注入事件循环，
    导致 asyncio.run() 检测到已有循环而报 RuntimeWarning。
    此补丁确保在新线程中总是创建全新的事件循环来运行服务器。
    """
    import uvicorn

    _original_run = uvicorn.Server.run

    def _patched_run(self, sockets=None):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.serve(sockets=sockets))
        finally:
            loop.close()

    uvicorn.Server.run = _patched_run


_patch_uvicorn_for_debug()

logging.basicConfig(
    format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class ChatServer:
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.ws_loop: asyncio.AbstractEventLoop | None = None
        self.ws_connection = None
        self.response_buffer: dict[str, str] = {}
        # 替换 threading.Event 为 asyncio.Future
        self.response_futures: dict[str, asyncio.Future] = {}
        self.skills_list: list = []  # 存储从WebSocket获取的技能列表

    def _build_system_message(self, **kwargs) -> dict:
        """构建工具消息格式"""
        message = {
            "type": "system"
        }
        message.update(kwargs)
        return message

    def _build_user_message(self, message_id: str, text: str) -> dict:
        """构建用户消息格式，给大模型分析。"""
        return {
            "id": message_id,
            "type": "user",
            "text": text,
        }

    async def _send_user_message(self, text: str) -> str:
        """通过现有 websocket 连接发送 user 消息。"""
        if self.ws_connection is None:
            raise RuntimeError("WebSocket 未连接")

        message_id = str(uuid.uuid4())
        payload = self._build_user_message(message_id, text)
        self.response_buffer[message_id] = ""
        # 创建 Future 对象用于异步等待响应
        self.response_futures[message_id] = asyncio.Future()
        await self.ws_connection.send(json.dumps(payload, ensure_ascii=False))
        logger.info(f"已发送消息: {payload}")
        return message_id

    async def _send_system_message(self, action: str, **kwargs) -> str:
        """通过现有 websocket 连接发送 system 消息。"""
        if self.ws_connection is None:
            raise RuntimeError("WebSocket 未连接")

        message_id = str(uuid.uuid4())
        payload = self._build_system_message(action=action, **kwargs)
        await self.ws_connection.send(json.dumps(payload, ensure_ascii=False))
        logger.info(f"已发送系统消息: {payload}")
        return message_id

    async def _handle_stream_message(self, message_id: str, msg_type: str, response: dict) -> None:
        """处理流式消息（start、chunk、end类型）"""
        if msg_type == "start":
            self.response_buffer[message_id] = ""
        elif msg_type == "chunk":
            # 累积响应片段
            chunk = response.get("chunk", "")
            self.response_buffer[message_id] = self.response_buffer.get(message_id, "") + chunk

        elif msg_type == "end":
            future = self.response_futures.get(message_id)
            if future and not future.done():
                future.set_result(self.response_buffer[message_id])

    async def _handle_tool_message(self, message_id: str, response: dict) -> None:
        """处理工具调用结果消息"""
        action = response.get("action")

    async def _handle_get_skills_response(self, response: dict) -> None:
        """处理获取技能列表的响应"""
        try:
            skills_data = response.get("skills", [])
            if skills_data:
                self.skills_list = skills_data
                logger.info(f"成功获取到 {len(skills_data)} 个技能数据")
            else:
                logger.warning("获取到的技能列表为空")
        except Exception as e:
            logger.error(f"处理技能列表响应失败: {e}")
            self.skills_list = []

    async def _handle_system_message(self, message_id: str, response: dict) -> None:
        """处理系统消息"""
        action = response.get("action")
        if action == "get_skills":
            await self._handle_get_skills_response(response)

    async def _ws_client_loop(self) -> None:
        """连接 WebSocket 服务器并打印接收数据。"""
        self.ws_loop = asyncio.get_running_loop()
        try:
            logger.info(f"WebSocket client connecting: {self.ws_url}")
            async with websockets.connect(self.ws_url) as websocket:
                self.ws_connection = websocket
                logger.info("WebSocket client connected")

                # 连接成功后自动发送获取技能列表的消息
                try:
                    await self._send_system_message(action="get_skills")
                except Exception as e:
                    logger.warning(f"发送获取技能列表请求失败: {e}")

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
                        elif msg_type == "system":
                            await self._handle_system_message(message_id, response)
                        elif msg_type == "error":
                            error_msg = response.get("error", "未知错误")
                            self.response_buffer[message_id] = f"❌ 错误: {error_msg}"
                            future = self.response_futures.get(message_id)
                            if future and not future.done():
                                future.set_result(self.response_buffer[message_id])

                    except json.JSONDecodeError as e:
                        logger.error(f"JSON 解析失败: {e}, 原始消息: {message}")
                    except Exception as e:
                        logger.exception(f"处理 WebSocket 消息时出错: {e}")
        except Exception as e:
            logger.exception(f"WebSocket client error: {e}")
        finally:
            self.ws_connection = None
            # 清理未完成的 futures
            for future in self.response_futures.values():
                if not future.done():
                    future.set_exception(RuntimeError("WebSocket 连接已关闭"))

    async def respond(self, message, history):
        """异步版本的响应函数，适配Gradio异步模式"""
        history = history or []
        if not message:
            yield "", history
            return

        # 先把用户消息和空的助手消息放入历史，立即刷新 UI
        history = history + [
            {"role": "user", "content": message},
            {"role": "assistant", "content": ""},
        ]
        yield "", history

        try:
            if self.ws_connection is None:
                raise RuntimeError("WebSocket 连接尚未建立")

            # 直接异步调用发送消息
            message_id = await self._send_user_message(message)

            future = self.response_futures.get(message_id)
            if not future:
                raise RuntimeError("未找到响应Future")

            deadline = time.time() + 600
            last_text = ""

            # 打字机式流式刷新
            while time.time() < deadline:
                current_text = self.response_buffer.get(message_id, "")
                if current_text != last_text:
                    history[-1]["content"] = current_text
                    last_text = current_text
                    yield "", history

                # 检查future是否完成，非阻塞
                if future.done():
                    break
                await asyncio.sleep(0.05)

            # 结束后再做一次最终刷新
            final_text = self.response_buffer.get(message_id, "")
            if final_text:
                history[-1]["content"] = final_text
            elif time.time() >= deadline:
                history[-1]["content"] = "(响应超时，请稍后重试)"
            yield "", history

            # 清理资源
            await self.response_futures.pop(message_id, None)
            self.response_buffer.pop(message_id, None)

        except Exception as e:
            logger.exception(f"发送 websocket 消息失败: {e}")
            history[-1]["content"] = f"❌ 发送失败: {str(e)}"
            yield "", history

    def create_skills_tab(self):
        """创建技能配置tab的UI框架 - 使用Gradio组件动态渲染"""

        # 最大支持的技能数量（用于预创建组件）
        MAX_SKILLS = 50

        async def refresh_skills():
            """刷新技能列表：先发送 WebSocket 请求获取最新数据，再更新组件"""
            try:
                if self.ws_connection is not None:
                    await self._send_system_message(action="get_skills")
                    await asyncio.sleep(1)
                    status_msg = f"✅ 已加载 {len(self.skills_list)} 个技能"
                else:
                    status_msg = "⚠️ WebSocket 未连接，显示缓存数据"
            except Exception as e:
                logger.warning(f"刷新技能列表时发送请求失败: {e}")
                status_msg = f"⚠️ 请求失败: {e}，显示缓存数据"

            # 构建每个技能卡片的更新值
            updates = []
            skills_data = self.skills_list if self.skills_list else []

            for i in range(MAX_SKILLS):
                if i < len(skills_data):
                    skill = skills_data[i]
                    emoji = skill.get("emoji", "🔧")
                    name = skill.get("name", "未知技能")
                    description = skill.get("description", "")
                    enabled = skill.get("enabled", False)
                    primary_env = skill.get("primaryEnv", "")

                    # 状态徽标
                    status_badge = "🟢 已启用" if enabled else "⚪ 未启用"

                    # 卡片容器 - 可见
                    updates.append(gr.update(visible=True))
                    # 技能信息（emoji + 名称 + 状态 + 描述）
                    updates.append(gr.update(
                        value=f"**{emoji} {name}** &nbsp;&nbsp; `{status_badge}`\n\n{description}"
                    ))
                    # 启用/禁用开关
                    updates.append(gr.update(
                        value=enabled, interactive=True,
                        label="已启用" if enabled else "未启用"
                    ))
                    # API Key 密码框 - 仅当 primaryEnv 不为空时显示
                    has_env = bool(primary_env)
                    updates.append(gr.update(visible=has_env, value=primary_env if has_env else ""))
                    # 显示/隐藏明文按钮
                    updates.append(gr.update(visible=has_env, value="👁️"))
                    # 显示/隐藏保存按钮
                    updates.append(gr.update(visible=has_env, value="💾 保存"))
                else:
                    # 隐藏多余的卡片
                    updates.append(gr.update(visible=False))
                    updates.append(gr.update())
                    updates.append(gr.update())
                    updates.append(gr.update(visible=False))
                    updates.append(gr.update(visible=False))
                    updates.append(gr.update(visible=False))

            # 最后追加 status_display
            enabled_count = sum(1 for s in skills_data if s.get("enabled", False))
            if skills_data:
                status_text = f"{status_msg}  ·  共 {len(skills_data)} 个技能，已启用 {enabled_count}"
            else:
                status_text = status_msg
            updates.append(gr.update(value=status_text))

            return updates

        async def toggle_skill(skill_index: int, enabled: bool):
            """启用或禁用技能"""
            skills_data = self.skills_list if self.skills_list else []
            if skill_index >= len(skills_data):
                return gr.update()

            skill = skills_data[skill_index]
            skill_name = skill.get("name", "")

            # 增加判断，避免无意义的调用
            if skill.get("enabled") == enabled:
                logger.info(f"技能 {skill_name} 的状态已是 {enabled}，跳过切换")
                return gr.update(label="已启用" if enabled else "未启用")

            action = "enable_skill" if enabled else "disable_skill"
            try:
                if self.ws_connection is not None:
                    await self._send_system_message(action=action, skill_name=skill_name)
                    await asyncio.sleep(0.5)
                    logger.info(f"已发送 {action} 请求: {skill_name}")
                else:
                    logger.warning("WebSocket 未连接，无法切换技能状态")
            except Exception as e:
                logger.warning(f"切换技能状态失败: {e}")
            return gr.update(label="已启用" if enabled else "未启用")

        # === 构建 UI ===
        # 顶部操作栏：标题 + 刷新按钮 + 状态
        with gr.Row(equal_height=True):
            with gr.Column(scale=1, min_width=100):
                refresh_btn = gr.Button("🔄 刷新", variant="secondary", size="sm")
            with gr.Column(scale=5):
                status_display = gr.Markdown(value="⏳ 等待加载...")

        # 预创建技能卡片组件
        skill_cards = []       # 每个元素: (group, info_md, toggle, btn, env_input, eye_btn)
        all_outputs = []       # 所有需要更新的组件，按顺序排列

        for i in range(MAX_SKILLS):
            with gr.Group(visible=False, elem_classes="skill-card") as card_group:
                # 第一行：技能信息 + 操作按钮
                with gr.Row(equal_height=True):
                    with gr.Column(scale=1, min_width=50):
                        toggle = gr.Checkbox(value=False, interactive=True)
                    with gr.Column(scale=5, min_width=300):
                        info_md = gr.Markdown(value="")
                # 第二行：API Key + 右侧按钮（眼睛 + 保存纵向排列）
                with gr.Row():
                    env_input = gr.Textbox(
                        label="🔑 API Key",
                        value="",
                        type="password",
                        visible=False,
                        interactive=True,
                        scale=8,
                        container=True
                    )
                    with gr.Column(scale=1, min_width=50):
                        eye_btn = gr.Button(
                            "👁️",
                            visible=False,
                            size="sm",
                            variant="secondary",
                            min_width=40,
                        )
                        save_btn = gr.Button(
                            "💾 保存",
                            visible=False,
                            size="sm",
                            variant="primary",
                            min_width=40,
                        )

            skill_cards.append((card_group, info_md, toggle, env_input, eye_btn, save_btn))
            all_outputs.extend([card_group, info_md, toggle, env_input, eye_btn, save_btn])

            # 为每个开关绑定事件（使用闭包捕获索引）
            def make_toggle_handler(idx):
                async def handler(enabled):
                    return await toggle_skill(idx, enabled)
                return handler

            toggle.change(fn=make_toggle_handler(i), inputs=[toggle], outputs=[toggle])

            # 眼睛按钮点击：在明文和密文之间切换
            # 使用 State 追踪当前显示状态
            env_visible_state = gr.State(value=False)

            def make_eye_toggle_handler(env_tb, state):
                def handler(current_state):
                    if current_state:
                        # 当前是明文，切换为密文
                        return gr.update(type="password"), gr.update(value="👁️"), False
                    else:
                        # 当前是密文，切换为明文
                        return gr.update(type="text"), gr.update(value="🔒"), True
                return handler

            eye_btn.click(
                fn=make_eye_toggle_handler(env_input, env_visible_state),
                inputs=[env_visible_state],
                outputs=[env_input, eye_btn, env_visible_state]
            )

            # 保存按钮点击：将 API Key 通过 WebSocket 发送到服务器
            def make_save_handler(idx):
                async def handler(api_key_value):
                    skills_data = self.skills_list if self.skills_list else []
                    if idx >= len(skills_data):
                        return gr.update(value="❌ 保存失败")

                    skill = skills_data[idx]
                    skill_name = skill.get("name", "")
                    env_name = skill.get("primaryEnv", "")

                    try:
                        if self.ws_connection is not None:
                            await self._send_system_message(
                                action="save_api_key",
                                skill_name=skill_name,
                                env_name=env_name,
                                api_key=api_key_value
                            )
                            await asyncio.sleep(0.3)
                            logger.info(f"已发送保存 API Key 请求: 技能={skill_name}")
                            return gr.update(value="✅ 已保存")
                        else:
                            logger.warning("WebSocket 未连接，无法保存 API Key")
                            return gr.update(value="⚠️ 未连接")
                    except Exception as e:
                        logger.warning(f"保存 API Key 失败: {e}")
                        return gr.update(value="❌ 保存失败")
                return handler

            save_btn.click(
                fn=make_save_handler(i),
                inputs=[env_input],
                outputs=[save_btn]
            )

        # 追加 status_display 到输出列表
        all_outputs.append(status_display)

        # 使用定时器自动刷新一次（3秒后，等待WebSocket连接建立并获取数据）
        timer = gr.Timer(value=3, active=True)
        timer.tick(fn=refresh_skills, outputs=all_outputs).then(
            fn=lambda: gr.Timer(active=False),
            outputs=[timer]
        )

        # 手动刷新按钮事件
        refresh_btn.click(fn=refresh_skills, outputs=all_outputs)

    async def run(self) -> None:
        """异步版本的run方法，统一在主线程事件循环中运行"""
        with gr.Blocks(title="Claw 机器人") as demo:
            gr.Markdown("# Claw 机器人")

            # 创建tab界面
            with gr.Tabs():
                # AI聊天tab
                with gr.TabItem("AI 聊天"):
                    chatbot = gr.Chatbot(height=500)
                    msg = gr.Textbox(label="输入消息", placeholder="请输入您的问题...")
                    send = gr.Button("发送")

                    # 绑定异步响应函数
                    send.click(self.respond, [msg, chatbot], [msg, chatbot])
                    msg.submit(self.respond, [msg, chatbot], [msg, chatbot])

                # 技能配置tab
                with gr.TabItem("技能配置"):
                    self.create_skills_tab()

        demo.queue()

        # 启动WebSocket客户端循环（作为异步任务）
        ws_task = asyncio.create_task(self._ws_client_loop())

        # 启动Gradio（异步模式，共享事件循环）
        demo.launch(prevent_thread_lock=True)

        logger.info("Gradio应用已启动")

        # 等待WebSocket任务结束（保持主线程运行）
        await ws_task


async def main() -> None:
    """异步主函数，启动主线程事件循环"""
    ws_url = os.getenv("WS_URL", "ws://localhost:4567")
    server = ChatServer(ws_url)
    await server.run()


if __name__ == "__main__":
    # 启动asyncio事件循环，统一调度所有异步任务
    asyncio.run(main())