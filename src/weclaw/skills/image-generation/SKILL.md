---
name: image-generation
description: Generate images from text prompts and perform image editing with DashScope QwenImage MCP service.
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

# image-generation (MCP)

Generate images from text prompts and perform image editing with DashScope 

## Prerequisites

- DashScope API key from [阿里云百炼](https://bailian.console.aliyun.com/)
- `mcp_client.py` in workspace

## Quick Start

Python command compatibility:

```bash
PYTHON_CMD=$(command -v python3 >/dev/null 2>&1 && echo python3 || echo python)
```

Load API key from environment variable:

```python
import os
api_key = os.getenv("DASHSCOPE_API_KEY")
```

Step 1: List all tools.

```bash
$PYTHON_CMD mcp_client.py \
  -u https://dashscope.aliyuncs.com/api/v1/mcps/QwenImage/sse \
  -k $DASHSCOPE_API_KEY \
  list-tools
```

Step 2: Choose the image-generation tool from the list.

Step 3: Call the selected tool.

```bash
$PYTHON_CMD mcp_client.py \
  -u https://dashscope.aliyuncs.com/api/v1/mcps/QwenImage/sse \
  -k $DASHSCOPE_API_KEY \
  call-tool <TOOL_NAME> -a '{"prompt": "A cinematic sunset over a cyberpunk city"}'
```

## Notes

- Always use `list-tools` first to confirm the exact tool name and parameter schema.
- Use clear prompts for better image quality.
- Watch DashScope quota and rate limits.
