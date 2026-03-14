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
        self.skills_list: list = []  # 存储从 WebSocket 获取的技能列表
        self.models_list: list[str] = []  # 可用模型列表
        self.default_model: str = ""  # 默认模型
        self.current_model: str = ""  # 当前选中的模型

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

    async def _handle_get_models_response(self, response: dict) -> None:
        """处理获取模型列表的响应"""
        try:
            self.models_list = response.get("models", [])
            self.default_model = response.get("default", "")
            self.current_model = response.get("current", self.default_model)
            logger.info(f"获取到 {len(self.models_list)} 个可用模型，当前: {self.current_model}")
        except Exception as e:
            logger.error(f"处理模型列表响应失败: {e}")

    async def _handle_system_message(self, message_id: str, response: dict) -> None:
        """处理系统消息"""
        action = response.get("action")
        if action == "get_skills":
            await self._handle_get_skills_response(response)
        elif action == "get_models":
            await self._handle_get_models_response(response)

    async def _ws_client_loop(self) -> None:
        """连接 WebSocket 服务器并打印接收数据。"""
        self.ws_loop = asyncio.get_running_loop()
        try:
            logger.info(f"WebSocket client connecting: {self.ws_url}")
            async with websockets.connect(self.ws_url) as websocket:
                self.ws_connection = websocket
                logger.info("WebSocket client connected")

                # 连接成功后自动发送获取技能列表和模型列表的消息
                try:
                    await self._send_system_message(action="get_skills")
                    await self._send_system_message(action="get_models")
                except Exception as e:
                    logger.warning(f"发送初始化请求失败: {e}")

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
        """创建技能配置tab的UI框架 - 使用分页 + Gradio组件动态渲染"""

        # 每页显示的技能数量
        SKILLS_PER_PAGE = 20

        def _build_page_updates(page: int):
            """根据当前页码构建所有组件的更新值列表（纯数据逻辑，不涉及网络请求）"""
            skills_data = self.skills_list if self.skills_list else []
            total = len(skills_data)
            total_pages = max(1, (total + SKILLS_PER_PAGE - 1) // SKILLS_PER_PAGE)

            # 确保页码在有效范围内
            page = max(0, min(page, total_pages - 1))

            start = page * SKILLS_PER_PAGE
            end = min(start + SKILLS_PER_PAGE, total)

            updates = []
            for i in range(SKILLS_PER_PAGE):
                skill_idx = start + i
                if skill_idx < end:
                    skill = skills_data[skill_idx]
                    emoji = skill.get("emoji", "🔧")
                    name = skill.get("name", "未知技能")
                    description = skill.get("description", "")
                    enabled = skill.get("enabled", False)
                    primary_env = skill.get("primaryEnv", "")
                    env_name = skill.get("envName", "")
                    builtin = skill.get("builtin", True)

                    # 来源标签
                    source_tag = "openclaw-bundled" if builtin else "third-party"
                    source_color = "#6b7280" if builtin else "#2563eb"
                    tags_html = (
                        f'<span style="display:inline-block;padding:2px 10px;border-radius:12px;'
                        f'border:1px solid {source_color};color:{source_color};font-size:12px;">'
                        f'{source_tag}</span>'
                    )

                    # 卡片容器 - 可见
                    updates.append(gr.update(visible=True))
                    # 技能名称（粗体）+ 描述
                    updates.append(gr.update(
                        value=f"**{name}**\n\n{description}"
                    ))
                    # 标签行
                    updates.append(gr.update(value=tags_html, visible=True))
                    # 启用/禁用按钮
                    btn_label = "Disable" if enabled else "Enable"
                    btn_variant = "secondary" if enabled else "primary"
                    updates.append(gr.update(value=btn_label, variant=btn_variant))
                    # API Key 行容器 - 仅当 envName 不为空时显示
                    has_env = bool(env_name)
                    updates.append(gr.update(visible=has_env))  # env_row
                    # API Key 密码框
                    env_label = f"API key" if not env_name else f"{env_name}"
                    updates.append(gr.update(visible=has_env, value=primary_env if has_env else "", label=env_label))
                    # 保存按钮
                    updates.append(gr.update(visible=has_env, value="Save key"))
                else:
                    # 隐藏多余的卡片
                    updates.append(gr.update(visible=False))  # card_group
                    updates.append(gr.update())                # info_md
                    updates.append(gr.update(visible=False))   # tags_html
                    updates.append(gr.update())                # toggle_btn
                    updates.append(gr.update(visible=False))   # env_row
                    updates.append(gr.update(visible=False))   # env_input
                    updates.append(gr.update(visible=False))   # save_btn

            # 状态文本
            enabled_count = sum(1 for s in skills_data if s.get("enabled", False))
            if skills_data:
                status_text = f"共 {total} 个技能，已启用 {enabled_count} 个"
            else:
                status_text = "暂无技能数据"

            # 页码信息
            page_text = f"第 {page + 1} / {total_pages} 页"

            # 上一页/下一页按钮的交互状态
            prev_interactive = page > 0
            next_interactive = page < total_pages - 1

            updates.append(gr.update(value=status_text))       # status_display
            updates.append(gr.update(value=page_text))         # page_info
            updates.append(gr.update(interactive=prev_interactive))  # prev_btn
            updates.append(gr.update(interactive=next_interactive))  # next_btn
            updates.append(page)  # current_page State

            return updates

        async def refresh_skills(current_page):
            """刷新技能列表：先发送 WebSocket 请求获取最新数据，再更新组件"""
            try:
                if self.ws_connection is not None:
                    await self._send_system_message(action="get_skills")
                    await asyncio.sleep(1)
                else:
                    logger.warning("WebSocket 未连接，显示缓存数据")
            except Exception as e:
                logger.warning(f"刷新技能列表时发送请求失败: {e}")

            # 刷新后回到第一页
            return _build_page_updates(0)

        def go_prev_page(current_page):
            """上一页"""
            new_page = max(0, current_page - 1)
            return _build_page_updates(new_page)

        def go_next_page(current_page):
            """下一页"""
            skills_data = self.skills_list if self.skills_list else []
            total_pages = max(1, (len(skills_data) + SKILLS_PER_PAGE - 1) // SKILLS_PER_PAGE)
            new_page = min(current_page + 1, total_pages - 1)
            return _build_page_updates(new_page)

        async def toggle_skill(slot_index: int, current_page):
            """启用或禁用技能，slot_index 是页面内的槽位索引"""
            skills_data = self.skills_list if self.skills_list else []
            real_index = current_page * SKILLS_PER_PAGE + slot_index
            if real_index >= len(skills_data):
                return gr.update(), gr.update()

            skill = skills_data[real_index]
            skill_name = skill.get("name", "")
            currently_enabled = skill.get("enabled", False)

            # 切换状态
            action = "disable_skill" if currently_enabled else "enable_skill"
            try:
                if self.ws_connection is not None:
                    await self._send_system_message(action=action, skill_name=skill_name)
                    await asyncio.sleep(0.5)
                    logger.info(f"已发送 {action} 请求: {skill_name}")
                    # 更新本地缓存
                    skill["enabled"] = not currently_enabled
                else:
                    logger.warning("WebSocket 未连接，无法切换技能状态")
            except Exception as e:
                logger.warning(f"切换技能状态失败: {e}")

            new_enabled = skill.get("enabled", False)
            btn_label = "Disable" if new_enabled else "Enable"
            btn_variant = "secondary" if new_enabled else "primary"

            # 更新标签
            builtin = skill.get("builtin", True)
            source_tag = "openclaw-bundled" if builtin else "third-party"
            source_color = "#6b7280" if builtin else "#2563eb"
            tags_html = (
                f'<span style="display:inline-block;padding:2px 10px;border-radius:12px;'
                f'border:1px solid {source_color};color:{source_color};font-size:12px;">'
                f'{source_tag}</span>'
            )

            return gr.update(value=btn_label, variant=btn_variant), gr.update(value=tags_html)

        # === 构建 UI ===
        # 分页状态
        current_page = gr.State(value=0)

        # 顶部操作栏：刷新按钮 + 分页控制 + 状态
        with gr.Row(equal_height=True):
            with gr.Column(scale=1, min_width=80):
                refresh_btn = gr.Button("🔄 刷新", variant="secondary", size="sm")
            with gr.Column(scale=1, min_width=80):
                prev_btn = gr.Button("◀ 上一页", size="sm", interactive=False)
            with gr.Column(scale=1, min_width=80):
                page_info = gr.Markdown(value="第 1 / 1 页")
            with gr.Column(scale=1, min_width=80):
                next_btn = gr.Button("下一页 ▶", size="sm", interactive=False)
            with gr.Column(scale=3):
                status_display = gr.Markdown(value="⏳ 等待加载...")

        # 预创建技能卡片组件
        skill_cards = []
        all_outputs = []       # 所有需要更新的组件，按顺序排列

        for i in range(SKILLS_PER_PAGE):
            with gr.Group(visible=False, elem_classes="skill-card") as card_group:
                # 第一行：技能信息 + 操作按钮
                with gr.Row(equal_height=True):
                    with gr.Column(scale=5, min_width=300):
                        info_md = gr.Markdown(value="")
                        tags_html = gr.HTML(value="", visible=False)
                    with gr.Column(scale=1, min_width=80):
                        toggle_btn = gr.Button("Enable", size="sm", variant="secondary")
                # 第二行：API Key + Save key 按钮
                with gr.Row(visible=False) as env_row:
                    env_input = gr.Textbox(
                        label="API key",
                        value="",
                        type="password",
                        visible=False,
                        interactive=True,
                        scale=8,
                        container=True
                    )
                    with gr.Column(scale=2, min_width=120):
                        save_btn = gr.Button(
                            "Save key",
                            visible=False,
                            size="sm",
                            variant="stop",
                            min_width=100,
                        )

            skill_cards.append((card_group, info_md, tags_html, toggle_btn, env_row, env_input, save_btn))
            all_outputs.extend([card_group, info_md, tags_html, toggle_btn, env_row, env_input, save_btn])

            # 为每个 Enable/Disable 按钮绑定事件（使用闭包捕获槽位索引）
            def make_toggle_handler(slot_idx):
                async def handler(cur_page):
                    return await toggle_skill(slot_idx, cur_page)
                return handler

            toggle_btn.click(
                fn=make_toggle_handler(i),
                inputs=[current_page],
                outputs=[toggle_btn, tags_html]
            )

            # 保存按钮点击：将 API Key 通过 WebSocket 发送到服务器
            def make_save_handler(slot_idx):
                async def handler(api_key_value, cur_page):
                    skills_data = self.skills_list if self.skills_list else []
                    real_idx = cur_page * SKILLS_PER_PAGE + slot_idx
                    if real_idx >= len(skills_data):
                        return gr.update(value="❌ 保存失败")

                    skill = skills_data[real_idx]
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
                inputs=[env_input, current_page],
                outputs=[save_btn]
            )

        # 追加分页控制相关输出
        all_outputs.append(status_display)
        all_outputs.append(page_info)
        all_outputs.append(prev_btn)
        all_outputs.append(next_btn)
        all_outputs.append(current_page)

        # 使用定时器自动刷新一次（3秒后，等待WebSocket连接建立并获取数据）
        timer = gr.Timer(value=3, active=True)
        timer.tick(fn=refresh_skills, inputs=[current_page], outputs=all_outputs).then(
            fn=lambda: gr.update(active=False),
            outputs=[timer]
        )

        # 手动刷新按钮事件
        refresh_btn.click(fn=refresh_skills, inputs=[current_page], outputs=all_outputs)

        # 翻页按钮事件
        prev_btn.click(fn=go_prev_page, inputs=[current_page], outputs=all_outputs)
        next_btn.click(fn=go_next_page, inputs=[current_page], outputs=all_outputs)

    async def run(self) -> None:
        """异步版本的run方法，统一在主线程事件循环中运行"""
        with gr.Blocks(title="Claw 机器人") as demo:
            gr.Markdown("# Claw 机器人")

            # 创建tab界面
            with gr.Tabs():
            # AI聊天tab
                with gr.TabItem("AI 聊天"):
                    # 模型选择区域
                    with gr.Row(equal_height=True):
                        model_dropdown = gr.Dropdown(
                            choices=[],
                            value="",
                            label="选择模型",
                            interactive=True,
                            scale=3,
                        )
                        refresh_models_btn = gr.Button("🔄 刷新模型", variant="secondary", size="sm", scale=1, min_width=100)
                        model_status = gr.Markdown(value="⭐ 当前模型: -")

                    chatbot = gr.Chatbot(height=500)
                    msg = gr.Textbox(label="输入消息", placeholder="请输入您的问题...")
                    send = gr.Button("发送")

                    # 模型切换处理
                    async def on_model_change(model_name):
                        """用户选择新模型时，发送切换消息到服务端"""
                        if not model_name:
                            return gr.update()
                        try:
                            if self.ws_connection is not None:
                                await self._send_system_message(action="switch_model", model_name=model_name)
                                self.current_model = model_name
                                await asyncio.sleep(0.3)
                                return gr.update(value=f"⭐ 当前模型: **{model_name}**")
                            else:
                                return gr.update(value="⚠️ WebSocket 未连接")
                        except Exception as e:
                            logger.warning(f"切换模型失败: {e}")
                            return gr.update(value=f"❌ 切换失败: {e}")

                    async def refresh_models():
                        """刷新可用模型列表"""
                        try:
                            if self.ws_connection is not None:
                                await self._send_system_message(action="get_models")
                                await asyncio.sleep(1)
                            models = self.models_list if self.models_list else []
                            current = self.current_model or self.default_model
                            return (
                                gr.update(choices=models, value=current if current in models else (models[0] if models else "")),
                                gr.update(value=f"⭐ 当前模型: **{current}**" if current else "⭐ 当前模型: -"),
                            )
                        except Exception as e:
                            logger.warning(f"刷新模型列表失败: {e}")
                            return gr.update(), gr.update()

                    # 绑定事件
                    model_dropdown.change(fn=on_model_change, inputs=[model_dropdown], outputs=[model_status])
                    refresh_models_btn.click(fn=refresh_models, outputs=[model_dropdown, model_status])

                    # 绑定异步响应函数
                    send.click(self.respond, [msg, chatbot], [msg, chatbot])
                    msg.submit(self.respond, [msg, chatbot], [msg, chatbot])

                    # 自动加载模型列表（延迟 3 秒等待 WebSocket 连接）
                    model_timer = gr.Timer(value=3, active=True)
                    model_timer.tick(fn=refresh_models, outputs=[model_dropdown, model_status]).then(
                        fn=lambda: gr.update(active=False),
                        outputs=[model_timer]
                    )

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