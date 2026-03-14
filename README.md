# Weclaw

Weclaw is a mini OpenClaw built on the Python LangChain framework. It is an easy-to-use personal assistant agent compatible with OpenClaw skills, suitable as a local/private prototype or a skill integration platform.

## 主要特性

- 基于 LangChain 的 agent 结构，便于扩展与定制。
- 与 OpenClaw skills 兼容，能复用现有技能集。
- 轻量、易上手，默认无需复杂配置即可运行。

## 要求

- Python 3.12+
- 使用远程 LLM 时，需配置相应的 API Key。打开仓库根目录的 `.env` 文件，按 `KEY=VALUE` 格式添加，例如：

```
DASHSCOPE_API_KEY=
LLM_MODEL=
LLM_PROVIDER=openai
BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```
保存文件并重新启动应用，或在当前终端加载该文件以使环境变量生效。

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

4. 启动 agent：

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

## Skills

将兼容的 OpenClaw skill 放入 `src/weclaw/skills` 目录（或按照项目中的 Skill 管理方式加载），即可被代理识别并调用。

