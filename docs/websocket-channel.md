# WebSocket 通道使用指南

Weclaw 简化了 OpenClaw 的 Channel 设计——启动后仅暴露一个 **WebSocket 服务端口**（默认 `ws://0.0.0.0:4567`），任何技能、前端界面或第三方程序都可以通过 WebSocket 连接，发送用户消息并接收大模型的流式响应。

## 架构概览

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Web UI      │     │ Telegram Bot │     │  飞书机器人   │
│  (Vue 3)     │     │  (python)    │     │  (python)    │
└──────┬───────┘     └──────┬───────┘     └──────┬───────┘
       │ ws                 │ ws                  │ ws
       └───────────┬────────┴─────────────────────┘
                   ▼
          ┌────────────────┐
          │  WebSocket     │
          │  Server :4567  │
          └────────┬───────┘
                   ▼
          ┌────────────────┐
          │  Agent (每连接  │
          │  独立实例)      │
          └────────┬───────┘
                   ▼
          ┌────────────────┐
          │  LLM (大模型)  │
          └────────────────┘
```

**核心设计**：
- 每个 WebSocket 连接对应一个独立的 `Client` 实例和 `Agent` 实例
- 支持多客户端同时连接，互不干扰
- 消息通过 JSON 格式编码，所有交互基于 `type` 字段路由

## 快速开始

### 启动 WebSocket 服务器

```bash
python -m weclaw.agent.main
```

输出示例：
```
============================================================
WebSocket服务器启动中...
监听地址: ws://0.0.0.0:4567
============================================================
服务器已启动，等待客户端连接...
按 Ctrl+C 停止服务器
============================================================
```

### 最简客户端示例（Python）

```python
import asyncio
import json
import uuid
import websockets

async def main():
    async with websockets.connect("ws://localhost:4567") as ws:
        # 1. 发送用户消息
        message_id = str(uuid.uuid4())
        await ws.send(json.dumps({
            "id": message_id,
            "type": "user",
            "text": "你好，请介绍一下你自己"
        }))

        # 2. 接收流式响应
        full_response = ""
        async for msg in ws:
            data = json.loads(msg)
            if data["id"] != message_id:
                continue

            if data["type"] == "start":
                print("--- 开始响应 ---")
            elif data["type"] == "chunk":
                chunk = data.get("chunk", "")
                full_response += chunk
                print(chunk, end="", flush=True)
            elif data["type"] == "end":
                print("\n--- 响应结束 ---")
                break
            elif data["type"] == "error":
                print(f"错误: {data.get('error')}")
                break

        print(f"\n完整响应: {full_response}")

asyncio.run(main())
```

### 最简客户端示例（JavaScript）

```javascript
const ws = new WebSocket('ws://localhost:4567')

ws.onopen = () => {
  const messageId = crypto.randomUUID()
  ws.send(JSON.stringify({
    id: messageId,
    type: 'user',
    text: '你好，请介绍一下你自己'
  }))
}

let buffer = ''
ws.onmessage = (event) => {
  const data = JSON.parse(event.data)
  switch (data.type) {
    case 'start':
      buffer = ''
      break
    case 'chunk':
      buffer += data.chunk || ''
      console.log('收到片段:', data.chunk)
      break
    case 'end':
      console.log('完整响应:', buffer)
      break
    case 'error':
      console.error('错误:', data.error)
      break
  }
}
```

## 消息协议

所有消息均为 **JSON 字符串**，通过 `type` 字段区分消息类型。

### 消息类型总览

| type | 方向 | 说明 |
|------|------|------|
| `user` | 客户端 → 服务端 | 用户消息，触发大模型处理 |
| `system` | 双向 | 系统控制消息（注入提示词、获取技能列表、切换模型等） |
| `tool` | 双向 | 工具调用消息（Agent 调用客户端侧工具） |
| `start` | 服务端 → 客户端 | 流式响应开始标志 |
| `chunk` | 服务端 → 客户端 | 流式响应文本片段 |
| `end` | 服务端 → 客户端 | 流式响应结束标志 |
| `error` | 服务端 → 客户端 | 错误消息 |

---

## 客户端 → 服务端 消息

### 1. 用户消息（user）

发送用户文本消息给大模型处理。位置信息（经纬度）直接组合到 `text` 字段中，无需单独的 `location` 字段。

**格式：**

```json
{
  "id": "unique-message-id",
  "type": "user",
  "text": "用户输入的文本内容",
  "image": "/path/to/image.png",     // 可选：图片本地路径
  "audio": "/path/to/audio.wav",     // 可选：音频本地路径
  "video": "/path/to/video.mp4",     // 可选：视频本地路径
  "image_b64": "base64-encoded...",  // 可选：图片 Base64 数据（与 image 二选一）
  "image_mime": "image/png",         // 可选：配合 image_b64 使用，默认 image/png
  "audio_b64": "base64-encoded...",  // 可选：音频 Base64 数据（与 audio 二选一）
  "audio_format": "wav",             // 可选：配合 audio_b64 使用，默认 wav
  "video_b64": "base64-encoded...",  // 可选：视频 Base64 数据（与 video 二选一）
  "video_mime": "video/mp4"          // 可选：配合 video_b64 使用，默认 video/mp4
}
```

**字段说明：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | ✅ | 消息唯一 ID，建议使用 UUID v4。服务端的响应会携带相同的 `id`，用于关联请求和响应 |
| `type` | string | ✅ | 固定值 `"user"` |
| `text` | string | ✅ | 用户消息文本。如果包含位置信息，将经纬度直接组合到此字段中（见下方示例） |
| `image` | string | ❌ | 图片本地文件路径 |
| `audio` | string | ❌ | 音频本地文件路径 |
| `video` | string | ❌ | 视频本地文件路径 |
| `image_b64` | string | ❌ | 图片 Base64 编码数据（与 `image` 二选一，`image_b64` 优先级更高） |
| `image_mime` | string | ❌ | 配合 `image_b64` 使用，指定 MIME 类型，默认 `image/png` |
| `audio_b64` | string | ❌ | 音频 Base64 编码数据（与 `audio` 二选一，`audio_b64` 优先级更高） |
| `audio_format` | string | ❌ | 配合 `audio_b64` 使用，指定音频格式，默认 `wav` |
| `video_b64` | string | ❌ | 视频 Base64 编码数据（与 `video` 二选一，`video_b64` 优先级更高） |
| `video_mime` | string | ❌ | 配合 `video_b64` 使用，指定 MIME 类型，默认 `video/mp4` |

> 💡 **路径 vs Base64**：对于本地技能（如 Telegram Bot、飞书机器人），推荐使用文件路径；对于 Web 前端等无法直接访问本地文件的场景，使用 Base64 编码传输。同时提供路径和 Base64 时，Base64 优先。

**普通文本消息示例：**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "user",
  "text": "今天天气怎么样？"
}
```

**位置消息示例：**

位置信息通过 `text` 字段传递，将经纬度和地名组合为自然语言描述：

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "user",
  "text": "用户发送了位置(上海市中心): 纬度 31.2304, 经度 121.4737"
}
```

**Base64 图片消息示例（如 Web 前端截图/上传）：**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "user",
  "text": "请分析这张图片",
  "image_b64": "iVBORw0KGgoAAAANSUhEUg...",
  "image_mime": "image/png"
}
```

**Base64 音频消息示例（如 Web 前端录音）：**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "user",
  "text": "",
  "audio_b64": "UklGRiQAAABXQVZFZm10...",
  "audio_format": "wav"
}
```

### 2. 系统消息（system）

用于系统级控制操作，通过 `action` 字段区分具体操作。

#### 2.1 注入系统提示词（prompt）

连接后首先发送，用于为当前会话注入额外的系统提示词（例如技能的 SKILL.md 内容）。

```json
{
  "type": "system",
  "action": "prompt",
  "text": "你是一个 Telegram 机器人助手..."
}
```

> 💡 提示词会在 Agent 初始化时被追加到默认系统提示词之后。必须在发送第一条 user 消息**之前**注入。

#### 2.2 获取技能列表（get_skills）

```json
{
  "type": "system",
  "action": "get_skills"
}
```

#### 2.3 启用技能（enable_skill）

```json
{
  "type": "system",
  "action": "enable_skill",
  "skill_name": "amap"
}
```

#### 2.4 禁用技能（disable_skill）

```json
{
  "type": "system",
  "action": "disable_skill",
  "skill_name": "amap"
}
```

#### 2.5 保存 API Key（save_api_key）

将 API Key 写入环境变量和 `.env` 文件。

```json
{
  "type": "system",
  "action": "save_api_key",
  "skill_name": "amap",
  "env_name": "DASHSCOPE_API_KEY",
  "api_key": "sk-xxxxxxxxxxxx"
}
```

#### 2.6 获取模型列表（get_models）

```json
{
  "type": "system",
  "action": "get_models"
}
```

#### 2.7 切换模型（switch_model）

```json
{
  "type": "system",
  "action": "switch_model",
  "model_name": "gpt-4o"
}
```

> ⚠️ 切换模型会销毁当前 Agent 实例，下次发送 user 消息时会用新模型重新初始化。

### 3. 工具响应消息（tool）

当 Agent 需要调用客户端侧的工具时，会发送 `tool` 类型消息给客户端，客户端处理完后需要回传结果。

```json
{
  "id": "request-id-from-server",
  "type": "tool",
  "result": "工具执行结果"
}
```

---

## 服务端 → 客户端 消息

### 1. 流式响应（start → chunk → end）

服务端收到 user 消息后，会以流式方式返回大模型的响应。三种消息共享同一个 `id`（与请求的 `id` 一致）。

#### start - 开始响应

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "start"
}
```

#### chunk - 文本片段

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "chunk",
  "chunk": "你好"
}
```

#### end - 响应结束

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "end"
}
```

**流式响应时序图：**

```
客户端                              服务端
  │                                   │
  │──── user (id=abc) ───────────────▶│
  │                                   │  Agent 开始处理
  │◀──── start (id=abc) ─────────────│
  │◀──── chunk (id=abc, "你") ───────│
  │◀──── chunk (id=abc, "好") ───────│
  │◀──── chunk (id=abc, "！") ───────│
  │◀──── chunk (id=abc, "我是") ─────│
  │◀──── chunk (id=abc, "AI") ───────│
  │◀──── end (id=abc) ───────────────│
  │                                   │
```

> 💡 客户端应在收到 `start` 时初始化缓冲区，收到 `chunk` 时累积文本，收到 `end` 时展示完整响应。

### 2. 错误消息（error）

当处理过程中发生异常时返回。

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "error",
  "error": "处理消息时发生异常: ..."
}
```

### 3. 系统响应消息（system）

服务端对系统消息的响应，通过 `action` 区分。

#### get_skills 响应

```json
{
  "id": "message-id",
  "type": "system",
  "action": "get_skills",
  "skills": [
    {
      "name": "amap",
      "description": "高德地图地理信息服务...",
      "emoji": "🗺️",
      "primaryEnv": "sk-xxx",
      "envName": "DASHSCOPE_API_KEY",
      "enabled": true,
      "builtin": true
    }
  ]
}
```

#### get_models 响应

```json
{
  "id": "message-id",
  "type": "system",
  "action": "get_models",
  "models": [
    {
      "name": "qwen-plus",
      "provider": "openai",
      "model": "qwen-plus-2025-07-28"
    }
  ],
  "default": "qwen-plus",
  "current": "qwen-plus"
}
```

#### enable_skill / disable_skill 响应

```json
{
  "id": "message-id",
  "type": "system",
  "action": "enable_skill",
  "skill_name": "amap",
  "success": true
}
```

#### save_api_key 响应

```json
{
  "id": "message-id",
  "type": "system",
  "action": "save_api_key",
  "skill_name": "amap",
  "success": true
}
```

#### switch_model 响应

```json
{
  "id": "message-id",
  "type": "system",
  "action": "switch_model",
  "model_name": "gpt-4o",
  "success": true
}
```

### 4. 工具调用消息（tool）

Agent 在处理用户消息的过程中，可能需要调用客户端侧注册的工具（如微信 channel 消息转发等）。

```json
{
  "id": "tool-request-id",
  "type": "tool",
  "action": "some_action",
  "param1": "value1"
}
```

客户端收到后执行工具操作，并回传结果（使用相同 `id`）。

#### 飞书机器人支持的 tool action

飞书机器人通过 `LARK_GREETING_CHAT_ID` 环境变量指定默认会话 ID，Agent 可通过工具消息向该会话发送文本、图片和文件。

##### send_text - 发送文本消息

```json
{
  "id": "tool-request-id",
  "type": "tool",
  "action": "send_text",
  "text": "你好，这是一条消息"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `text` | string | ✅ | 要发送的文本内容 |

##### send_pic - 发送图片消息

图片会先上传到飞书服务器获取 `image_key`，再以图片消息形式发送。

```json
{
  "id": "tool-request-id",
  "type": "tool",
  "action": "send_pic",
  "path": "~/Downloads/photo.png"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | string | ✅ | 本地图片文件路径，支持 `~` 展开 |

##### send_file - 发送文件消息

文件会先上传到飞书服务器获取 `file_key`，再以文件消息形式发送。飞书会根据文件后缀自动映射类型。

```json
{
  "id": "tool-request-id",
  "type": "tool",
  "action": "send_file",
  "path": "~/Documents/report.pdf"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | string | ✅ | 本地文件路径，支持 `~` 展开 |

**支持的文件类型映射：**

| 文件后缀 | 飞书 file_type |
|----------|---------------|
| `.opus` | opus |
| `.mp4` | mp4 |
| `.pdf` | pdf |
| `.doc` / `.docx` | doc |
| `.xls` / `.xlsx` | xls |
| `.ppt` / `.pptx` | ppt |
| 其他 | stream |

##### 工具消息响应格式

客户端处理完工具消息后，通过 WebSocket 回传结果给 Agent（使用相同 `id`）：

**成功响应：**

```json
{
  "id": "tool-request-id",
  "type": "tool",
  "result": {
    "status": "success",
    "action": "send_file",
    "path": "~/Documents/report.pdf"
  }
}
```

**失败响应：**

```json
{
  "id": "tool-request-id",
  "type": "tool",
  "result": {
    "status": "error",
    "error_msg": "文件发送失败: ~/Documents/report.pdf"
  }
}
```

---

## 连接生命周期

### 典型的会话流程

```
1. 客户端建立 WebSocket 连接
   └─▶ 服务端创建 Client 实例

2. [可选] 客户端发送 system/prompt 消息注入提示词
   └─▶ 服务端缓存提示词

3. [可选] 客户端发送 system/get_skills 或 system/get_models
   └─▶ 服务端返回列表数据

4. 客户端发送 user 消息
   └─▶ 服务端初始化 Agent（首次消息时触发，使用缓存的提示词）
   └─▶ Agent 调用大模型
   └─▶ 服务端流式返回 start → chunk... → end

5. 重复步骤 4（同一连接内的 Agent 保持上下文记忆）

6. 客户端断开连接
   └─▶ 服务端销毁 Client 和 Agent 实例，释放资源
```

### 重要特性

- **懒初始化**：Agent 不会在连接建立时立即创建，而是在收到第一条 user 消息时才初始化。这样 system/prompt 等预设消息可以在初始化前注入。
- **上下文保持**：同一 WebSocket 连接内的所有对话共享同一个 Agent 实例，大模型会记住之前的对话上下文。
- **并发处理**：同一连接内的多条 user 消息可以并发处理（通过 `asyncio.create_task`），每条消息通过 `id` 独立追踪。
- **资源清理**：连接断开时自动清理所有未完成的请求、取消运行中的任务、关闭 Agent。

---

## 消息工具函数

Weclaw 提供了 `weclaw.utils.message` 模块，封装了消息构建逻辑：

```python
from weclaw.utils.message import build_user_message, build_system_message, build_tool_message

# 构建用户消息
msg = build_user_message(
    message_id="uuid-xxx",
    text="你好"
)
# => {"id": "uuid-xxx", "type": "user", "text": "你好"}

# 构建包含位置信息的用户消息（经纬度组合到 text 字段）
msg = build_user_message(
    message_id="uuid-xxx",
    text="用户发送了位置(北京天安门): 纬度 39.9042, 经度 116.4074"
)
# => {"id": "uuid-xxx", "type": "user", "text": "用户发送了位置(北京天安门): 纬度 39.9042, 经度 116.4074"}

# 构建系统消息
msg = build_system_message(action="prompt", text="你是一个助手")
# => {"type": "system", "action": "prompt", "text": "你是一个助手"}

# 构建工具消息
msg = build_tool_message(message_id="uuid-xxx", result="执行成功")
# => {"id": "uuid-xxx", "type": "tool", "result": "执行成功"}
```

---

## 实战：开发一个 WebSocket 客户端技能

以 Telegram Bot 和飞书机器人为参考，开发一个新的客户端技能通常包含以下步骤：

### 1. 建立 WebSocket 连接并注入提示词

```python
import asyncio
import json
import websockets
from pathlib import Path
from weclaw.utils.message import build_user_message, build_system_message

async def connect_and_init(ws_url="ws://localhost:4567"):
    ws = await websockets.connect(ws_url)

    # 读取技能描述文件作为提示词
    skill_md = Path(__file__).parent.parent / "SKILL.md"
    prompt = skill_md.read_text(encoding="utf-8")

    # 注入提示词
    await ws.send(json.dumps(build_system_message(
        action="prompt",
        text=prompt
    )))

    return ws
```

### 2. 发送用户消息

```python
import uuid

async def send_user_message(ws, text, **kwargs):
    message_id = str(uuid.uuid4())
    request = build_user_message(message_id, text, **kwargs)
    await ws.send(json.dumps(request, ensure_ascii=False))
    return message_id
```

### 3. 接收并处理流式响应

```python
async def receive_response(ws, message_id):
    """接收完整的流式响应"""
    buffer = ""
    async for msg in ws:
        data = json.loads(msg)
        if data.get("id") != message_id:
            continue

        msg_type = data.get("type", "")

        if msg_type == "start":
            buffer = ""
        elif msg_type == "chunk":
            buffer += data.get("chunk", "")
        elif msg_type == "end":
            return buffer
        elif msg_type == "error":
            raise Exception(data.get("error", "未知错误"))

    return buffer
```

### 4. 断线重连机制

参考 Telegram Bot 的实现，推荐在生产环境中加入断线重连：

```python
async def websocket_loop(ws_url, shutdown_event):
    """带断线重连的 WebSocket 循环"""
    while not shutdown_event.is_set():
        try:
            async with websockets.connect(ws_url) as ws:
                # ... 注入提示词、处理消息 ...
                async for message in ws:
                    # 处理消息
                    pass
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            print(f"连接错误: {e}")
        finally:
            # 等待 10 秒后重连
            if not shutdown_event.is_set():
                try:
                    await asyncio.wait_for(
                        shutdown_event.wait(), timeout=10
                    )
                except asyncio.TimeoutError:
                    pass  # 超时后继续重连
```

---

## 现有客户端参考

| 客户端 | 语言 | 文件路径 | 说明 |
|--------|------|----------|------|
| Web UI | JavaScript | `web/src/composables/useWebSocket.js` | Vue 3 组合式 API 封装，支持流式渲染 |
| Telegram Bot | Python | `src/weclaw/skills/telegram/scripts/telegram_bot.py` | 异步客户端，带断线重连 |
| 飞书机器人 | Python | `src/weclaw/skills/feishu/scripts/feishu_bot.py` | 独立线程运行 asyncio 事件循环 |

---

## 常见问题

### Q: WebSocket 默认端口是什么？
**A**: 默认监听 `0.0.0.0:4567`，可在 `main.py` 中修改 `Server(host=..., port=...)` 参数。

### Q: 可以同时连接多个客户端吗？
**A**: 可以。每个 WebSocket 连接独立管理自己的 Agent 实例和对话上下文，互不干扰。

### Q: 消息 ID 有什么用？
**A**: `id` 是请求-响应的关联标识。由于同一连接可以并发发送多条消息，客户端需要通过 `id` 将服务端的流式响应（`start` / `chunk` / `end`）与对应的请求匹配起来。建议使用 UUID v4 生成。

### Q: 必须先发送 prompt 消息吗？
**A**: 不是必须的。如果不发送 `system/prompt`，Agent 会使用默认的系统提示词。但如果你的技能需要特定的行为指引（如 Telegram Bot 需要告诉 Agent 自己是 Telegram 机器人），建议在首次 user 消息之前注入。

### Q: 如何切换使用的大模型？
**A**: 发送 `system/switch_model` 消息。注意切换后当前 Agent 会被销毁，之前的对话上下文会丢失。

### Q: 连接断开后对话历史还在吗？
**A**: 不在。WebSocket 连接断开后，对应的 Agent 实例会被销毁，对话历史随之清除。重新连接会创建全新的 Agent。
