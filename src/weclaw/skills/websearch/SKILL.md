---
name: websearch
description: 网页搜索服务，支持增强意图识别的网页搜索。返回 AI 优化的结果，包括标题、URL、摘要、站点名称等，用于动态知识获取。使用 mcp_client.py 脚本调用。
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

智能网页搜索服务，返回针对 AI 处理优化的结构化结果。通过 `mcp_client.py` 脚本调用远程服务。

## Prerequisites

- DashScope API key from [阿里云百炼](https://bailian.console.aliyun.com/)
- `mcp_client.py` in workspace（已内置，无需安装任何额外依赖）

## Quick Start

Python command compatibility (some machines use `python`, others use `python3`):

```bash
PYTHON_CMD=$(command -v python3 >/dev/null 2>&1 && echo python3 || echo python)
```

Load API key from environment variable:

```python
import os
api_key = os.getenv("DASHSCOPE_API_KEY")
```

## Available Tools

### 1. bailian_web_search
搜索可用于查询百科知识、时事新闻、天气等信息

```bash
$PYTHON_CMD mcp_client.py --base-url https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/sse --api-key "$DASHSCOPE_API_KEY" call-tool bailian_web_search --args '{"query": "今天最新的军事新闻", "count": 5}'
```

## Notes

- 需要 DashScope API Key（环境变量 `DASHSCOPE_API_KEY`）
- 返回结果已针对 AI 消费优化
- 支持增强意图识别
- 注意 DashScope 配额限制
- **无需安装任何额外 Python 包，直接使用 mcp_client.py 即可**
- 如果以上工具列表不满足需求，可使用 `list-tools` 命令获取所有可用工具：
  ```bash
  $PYTHON_CMD mcp_client.py \
    -u https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/sse \
    -k $DASHSCOPE_API_KEY \
    list-tools
  ```
