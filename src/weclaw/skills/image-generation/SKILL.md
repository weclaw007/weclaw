---
name: image-generation
description: 图片生成服务，支持文生图和图片编辑。使用 weclaw.agent.mcp_client 模块调用 DashScope QwenImage MCP 服务。
homepage: https://dashscope.aliyuncs.com/api/v1/mcps/QwenImage/sse
metadata:
  {
    "openclaw":
      {
        "emoji": "🖼️",
        "primaryEnv": "DASHSCOPE_API_KEY",
        "requires": { "bins": ["python"] }
      },
  }
---

# image-generation (图片生成)

文本生成图片与图片编辑服务。通过 `python -m weclaw.agent.mcp_client` 调用远程服务。

## Prerequisites

- DashScope API key from [阿里云百炼](https://bailian.console.aliyun.com/)
- `weclaw.agent.mcp_client` 模块已内置，无需安装任何额外依赖

## Quick Start

Python command compatibility:

```bash
PYTHON_CMD=$(command -v python3 >/dev/null 2>&1 && echo python3 || echo python)
```

Step 1: List all tools.

> **重要：`-u`（--base-url）和 `-k`（--api-key）是必填参数，每次调用都必须传递，不可省略。`-k` 传入的是环境变量名（而非变量值），程序会自动读取环境变量。**

```bash
$PYTHON_CMD -m weclaw.agent.mcp_client \
  -u https://dashscope.aliyuncs.com/api/v1/mcps/QwenImage/sse \
  -k DASHSCOPE_API_KEY \
  list-tools
```

Step 2: Choose the image-generation tool from the list.

Step 3: Call the selected tool.

```bash
$PYTHON_CMD -m weclaw.agent.mcp_client \
  -u https://dashscope.aliyuncs.com/api/v1/mcps/QwenImage/sse \
  -k DASHSCOPE_API_KEY \
  call-tool <TOOL_NAME> -a '{"prompt": "A cinematic sunset over a cyberpunk city"}'
```

## Notes

- 需要 DashScope API Key（环境变量 `DASHSCOPE_API_KEY`）
- **每次调用必须同时提供 `-u`（base-url）和 `-k`（api-key，环境变量名）参数**
- 使用 `list-tools` 先确认可用的工具名和参数格式
- 使用清晰的 prompt 可获得更好的图片质量
- 注意 DashScope 配额限制
- **无需安装任何额外 Python 包，直接使用 `python -m weclaw.agent.mcp_client` 即可**
