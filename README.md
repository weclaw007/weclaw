# Weclaw

Weclaw is a mini OpenClaw built on the Python LangChain framework. It is an easy-to-use personal assistant agent compatible with OpenClaw skills, suitable as a local/private prototype or a skill integration platform.

## 快速上手

1. 克隆仓库：

```
git clone https://github.com/kkbig509/weclaw.git
cd your-repo
```

2. 安装：
推荐使用 python 虚拟环境
```
python3 -m venv .venv
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

5. 启动 agent：

先在一个终端启动 agent：

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



然后在另一个终端启动 server：

```
python -m weclaw.server.server


* Running on local URL:  http://127.0.0.1:7860
[2026-03-14 09:53:27,997] INFO httpx: HTTP Request: GET http://127.0.0.1:7860/gradio_api/startup-events "HTTP/1.1 200 OK"
[2026-03-14 09:53:28,167] INFO httpx: HTTP Request: GET https://api.gradio.app/pkg-version "HTTP/1.1 200 OK"
[2026-03-14 09:53:28,249] INFO httpx: HTTP Request: HEAD http://127.0.0.1:7860/ "HTTP/1.1 200 OK"
* To create a public link, set `share=True` in `launch()`.
```

启动后通过浏览器打开本地对话页面（默认地址通常为 http://localhost:7860，具体端口请参见项目配置）。

## 主要特性

- 基于 LangChain 的 agent 结构，便于扩展与定制。
- 与 OpenClaw skills 兼容，能复用现有技能集。
- 轻量、易上手，默认无需复杂配置即可运行。
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

## 要求

- Python 3.12+
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

