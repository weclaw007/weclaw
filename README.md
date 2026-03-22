# Weclaw

Weclaw is a mini OpenClaw built on the Python LangChain framework. It is an easy-to-use personal assistant agent compatible with OpenClaw skills, suitable as a local/private prototype or a skill integration platform.

![聊天页面](https://raw.githubusercontent.com/kkbig509/weclaw/main/chat.png "聊天页面")

![技能页面](https://raw.githubusercontent.com/kkbig509/weclaw/main/skills.png "技能页面")

## 快速上手

1. 克隆仓库：

```
git clone https://github.com/weclaw007/weclaw
cd your-repo
```

2. 安装：
推荐使用 python 虚拟环境
```
python3 -m venv .venv
// win
.venv/Scripts/activate

//mac or linux
source .venv/bin/activate


pip install -e .
```

3. 环境检查（CLI/agent）：

```
检查环境
python -m weclaw.cli.main doctor
安装技能，内置了一些技能，也可以使用 openclaw 技能
python -m weclaw.cli.main install
```

4. 快速调试（交互式命令行）：

无需启动 WebSocket 和 Web UI，直接运行 agent.py 即可进入交互式命令行模式，方便快速测试和调试：

```
python src/weclaw/agent/agent.py
```

启动后即可在终端中直接与 agent 对话，输入 `exit` 或 `quit` 退出。

5. 启动服务：

先在一个终端启动 agent（WebSocket 后端）：

```
python -m weclaw.agent.main


WebSocket服务器启动中...
监听地址: ws://0.0.0.0:4567
============================================================
[2026-03-14 09:52:57,997] INFO websockets.server: server listening on 0.0.0.0:4567
服务器已启动，等待客户端连接...
按 Ctrl+C 停止服务器
============================================================
```

然后在另一个终端启动 Web UI（Vue 前端）：

```
cd web
npm install   # 首次启动需要安装依赖
npm run dev


  VITE v6.x.x  ready in xxx ms

  ➜  Local:   http://localhost:3000/
  ➜  Network: use --host to expose
```

启动后通过浏览器打开 http://localhost:3000 即可进入对话页面。

> 💡 Web UI 基于 Vue 3 + Element Plus + Vite 构建，通过 WebSocket 与后端 agent 通信。Vite 开发服务器已配置代理，会自动将 WebSocket 请求转发到 `ws://localhost:4567`。



## Telegram Bot

Weclaw 内置了 Telegram 机器人技能，你可以通过 Telegram 随时随地与 AI 助手对话。

### 快速接入

1. 在 Telegram 中搜索 **BotFather**，发送 `/newbot` 创建机器人，获取 Bot Token
2. 将 Token 写入 `.env` 文件：`TELEGRAM_BOT_TOKEN=your-token-here`
3. 启动 Weclaw 后，在网页 Chat 界面中输入"启动 telegram bot"即可

> 📖 详细的创建步骤和使用说明请参阅 [Telegram Bot 使用指南](docs/telegram-bot.md)。

## 飞书机器人

Weclaw 内置了飞书（Lark）机器人技能，支持通过飞书自建应用与 AI 助手进行对话，基于 `lark-oapi` SDK 开发，采用长连接（WebSocket）方式接收消息。

### 支持功能

- 📝 文本消息：发送文本消息，AI 助手自动回复
- 🎙️ 语音消息：发送语音消息，AI 助手自动识别语音内容并回复
- 📍 位置消息：发送位置信息，AI 助手可获取经纬度和地名进行处理
- 🤖 命令控制：支持 `/start`、`/stop`、`/help` 命令
- 🔄 断线重连：WebSocket 连接断开后自动重连

### 快速接入

1. 在 [飞书开放平台](https://open.feishu.cn/) 创建自建应用，获取 App ID 和 App Secret
2. 在应用后台开启**机器人**能力，添加 `im:message` 等权限，并启用**长连接模式**
3. 将配置写入 `.env` 文件：
   ```
   LARK_APP_ID=your-app-id-here
   LARK_APP_SECRET=your-app-secret-here
   ```
4. 启动 Weclaw 后，在网页 Chat 界面中输入"启动飞书机器人"即可

> 💡 飞书机器人使用长连接方式与飞书服务器通信，无需配置公网回调地址，适合本地开发和内网部署。

## WebSocket 通道

Weclaw 简化了 OpenClaw 的 Channel 设计——启动后仅暴露一个 **WebSocket 服务端口**（默认 `ws://0.0.0.0:4567`），任何技能、前端界面或第三方程序都可以通过标准 WebSocket 协议接入。

### 核心特性

- **统一入口**：所有客户端（Web UI、Telegram Bot、飞书机器人等）都通过同一个 WebSocket 端口通信
- **流式响应**：大模型响应以 `start → chunk... → end` 方式流式推送，实时感知生成过程
- **独立实例**：每个 WebSocket 连接拥有独立的 Agent 和对话上下文，互不干扰
- **JSON 协议**：简洁的 JSON 消息格式，通过 `type` 字段路由，易于对接任何语言/平台
- **断线重连**：内置重连机制，连接断开后自动等待并重试

> 📖 完整的消息协议、代码示例和开发指南请参阅 [WebSocket 通道使用指南](docs/websocket-channel.md)。

## 定时任务

Weclaw 内置了定时任务功能，通过自然语言即可创建提醒，到期后 AI 主动推送消息。

### 快速体验

```
用户: 1分钟后提醒我喝水
AI:   好的，已设置 1 分钟后的提醒 ✅

（1分钟后，AI 主动推送）
AI:   ⏰ 提醒：该喝水了！
```

```
用户: 每隔1分钟帮我查一次北京天气，查10次
AI:   好的，已设置每 60 秒重复查询北京天气，最多执行 10 次 ✅

（每分钟触发一次）
AI:   ⏰ 北京当前天气：晴，气温 15°C 🌤️
```

### 核心特性

- ⚡ **精准触发**：基于 APScheduler AsyncIOScheduler，毫秒级精度，零轮询开销
- 💾 **持久化**：任务写入 SQLite，服务重启后自动恢复
- 🔁 **重复任务**：支持按固定间隔重复触发，可设置最大次数或无限循环
- 🤖 **大模型处理**：到期后由大模型决定响应方式，可联动天气、消息推送等工具
- 🗂️ **Session 隔离**：每个连接独立的任务数据库

> 📖 完整的设计原理、操作说明和技术细节请参阅 [定时任务使用指南](docs/timer-job-guide.md)。

## MCP 技能框架

Weclaw 内置了 [MCP（Model Context Protocol）](https://modelcontextprotocol.io/) 客户端框架，让你可以**零代码**接入任何标准 MCP 服务器，极速扩展 AI 助手的能力边界。

### 已内置的 MCP 技能

| 技能 | 说明 | 服务端点 |
|------|------|----------|
| 🗺️ **AMap 高德地图** | 地理编码、天气查询、路线规划、周边搜索等 | DashScope MCP |
| 🔍 **WebSearch 网页搜索** | 智能网页搜索，返回 AI 优化的结构化结果 | DashScope MCP |
| 🎨 **Image Generation** | AI 图片生成 | DashScope MCP |

### 为什么选择 MCP？

- **零代码接入**：只需编写一个 `SKILL.md` 描述文件，无需编写任何 Python 代码
- **内置 MCP 客户端**：`mcp_client.py` 开箱即用，自动处理 SSE 连接、认证和工具调用
- **即插即用**：将技能目录放入 `src/weclaw/skills/`，重启即可被 Agent 自动发现
- **生态兼容**：支持任何符合 MCP 标准的远程服务器

> 📖 想要添加自己的 MCP 技能？请参阅 [MCP 技能开发指南](docs/mcp-skill-guide.md)，只需 3 步，5 分钟即可完成。

## 主要特性

- 基于 LangChain 的 agent 结构，便于扩展与定制。
- 与 OpenClaw skills 兼容，能复用现有技能集。
- 轻量、易上手，默认无需复杂配置即可运行。
- **Vue Web UI**：基于 Vue 3 + Element Plus 构建的现代化 Web 界面，支持聊天对话、语音输入、技能管理等功能。
- **多模型支持**：通过统一的 `models.yaml` 配置文件管理所有厂商大模型，在 UI 中一键切换。
- **本地 Ollama 模型**：自动发现本地已安装的 Ollama 模型，无需额外配置即可使用。

## 模型选择

Weclaw 支持在 UI 界面中动态切换不同的大模型，包括云端 API 模型和本地 Ollama 模型。

### 支持的模型厂商

| 厂商 | Provider | 示例模型 |
|------|----------|---------|
| 阿里云 DashScope | `openai` | qwen-plus, qwen-turbo, qwen-max, qwen-vl |
| OpenAI | `openai` | gpt-4o, gpt-4o-mini |
| Anthropic | `anthropic` | claude-sonnet, claude-haiku |
| Google | `google_genai` | gemini-flash, gemini-pro |
| DeepSeek | `openai` | deepseek-chat, deepseek-reasoner |
| Ollama 本地 | `ollama` | 自动发现已安装的模型 |

### 配置模型

所有模型在项目根目录的 `models.yaml` 中统一配置：

```yaml
models:
  qwen-plus:
    provider: openai
    model: qwen-plus-2025-07-28
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    api_key_env: DASHSCOPE_API_KEY

  gpt-4o:
    provider: openai
    model: gpt-4o
    api_key_env: OPENAI_API_KEY

# 默认使用的模型
default: qwen-plus

# Ollama 本地模型自动发现
ollama:
  host: http://localhost:11434
  auto_discover: true
```

- **云端模型**：在 `models` 中添加配置项，填写 `provider`、`model`、`base_url`（可选）和 `api_key_env`。
- **本地 Ollama 模型**：开启 `auto_discover: true` 后自动发现本地已安装的模型，无需手动添加。
- **API Key**：仅在 `.env` 文件中配置，`models.yaml` 只引用环境变量名。

> 💡 关于 Ollama 的安装和模型下载，请参阅 [Ollama 使用指南](docs/ollama-guide.md)。

### 在 UI 中切换模型

启动后在 Web 页面顶部可以看到模型下拉选择框，支持：
- 从下拉列表中选择已配置的云端模型或本地 Ollama 模型
- 点击 🔄 按钮刷新模型列表（如刚安装了新的 Ollama 模型）
- 当前使用的模型会以 ⭐ 标记显示

## 技术栈

- **后端**：Python 3.10+、LangChain、WebSocket
- **前端**：Vue 3、Element Plus、Vite、markdown-it
- **通信**：WebSocket（前端通过 Vite 代理连接后端）

## 要求

- Python 3.10+
- Node.js 18+（用于 Web UI）
- 使用远程 LLM 时，需配置相应的 API Key。打开仓库根目录的 `.env` 文件，按 `KEY=VALUE` 格式添加，例如：

```
# 阿里云 DashScope
DASHSCOPE_API_KEY=your-key-here

# OpenAI
OPENAI_API_KEY=your-key-here

# Anthropic
ANTHROPIC_API_KEY=your-key-here

# Google Gemini
GOOGLE_API_KEY=your-key-here

# DeepSeek
DEEPSEEK_API_KEY=your-key-here
```
保存文件并重新启动应用，或在当前终端加载该文件以使环境变量生效。

## Skills

将兼容的 OpenClaw skill 放入 `src/weclaw/skills` 目录（或按照项目中的 Skill 管理方式加载），即可被代理识别并调用。

