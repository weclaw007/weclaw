---
name: websearch
description: 网页搜索服务，支持增强意图识别的网页搜索。返回 AI 优化的结果，包括标题、URL、摘要、站点名称等，用于动态知识获取。使用 weclaw.agent.mcp_client 模块调用。
homepage: https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/sse
metadata:
  {
    "openclaw":
      {
        "emoji": "🔍",
        "primaryEnv": "DASHSCOPE_API_KEY",
        "requires": { "bins": ["python"] }
      },
  }
---

# WebSearch 网页搜索

智能网页搜索服务，返回针对 AI 处理优化的结构化结果。通过 `python -m weclaw.agent.mcp_client` 调用远程服务。

## Prerequisites

- DashScope API key from [阿里云百炼](https://bailian.console.aliyun.com/)
- `weclaw.agent.mcp_client` 模块已内置，无需安装任何额外依赖

## Quick Start

Python command compatibility (some machines use `python`, others use `python3`):

```bash
PYTHON_CMD=$(command -v python3 >/dev/null 2>&1 && echo python3 || echo python)
```

## Supported Commands

### 1. bailian_web_search
搜索可用于查询百科知识、时事新闻、天气等信息

> **重要：`-u`（--base-url）和 `-k`（--api-key）是必填参数，每次调用都必须传递，不可省略。`-k` 传入的是环境变量名（而非变量值），程序会自动读取环境变量。**
>
> **参数格式：`-a` 支持 key=value 格式（推荐，跨平台兼容）和 JSON 格式，多个参数用空格分隔。如果值包含空格，需用双引号包裹，如 `-a query="latest AI news"`。**

```bash
$PYTHON_CMD -m weclaw.agent.mcp_client \
  -u https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/sse \
  -k DASHSCOPE_API_KEY \
  call_command bailian_web_search -a query="今天最新的军事新闻" count=5
```

## Notes

- 需要 DashScope API Key（环境变量 `DASHSCOPE_API_KEY`）
- **每次调用必须同时提供 `-u`（base-url）和 `-k`（api-key，环境变量名）参数**
- 返回结果已针对 AI 消费优化
- 支持增强意图识别
- 注意 DashScope 配额限制
- **无需安装任何额外 Python 包，直接使用 `python -m weclaw.agent.mcp_client` 即可**
- 如果以上工具列表不满足需求，可使用 `list-tools` 命令获取所有可用工具：
  ```bash
  $PYTHON_CMD -m weclaw.agent.mcp_client \
    -u https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/sse \
    -k DASHSCOPE_API_KEY \
    list-tools
  ```
