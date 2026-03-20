---
name: feishu
description: Use this skill to start and manage Feishu(飞书) (Lark) bot, send messages through Feishu bot, and interact with Feishu Open API. This skill provides Feishu bot functionality including message receiving, replying, and bot operations via lark-oapi SDK.
homepage: local
metadata:
  {
    "openclaw":
      {
        "emoji": "🐦",
        "primaryEnv": "LARK_APP_ID",
        "requires": { "bins": ["python", "python3"] }
      },
  }
---

# feishu

Use this skill to start and manage Feishu (Lark) bot, send messages through Feishu bot, and interact with Feishu Open API. This skill provides Feishu bot functionality including message receiving, replying, and bot operations via lark-oapi SDK.Use the `message` tool. No provider-specific `feishu` tool exposed to the agent.


## Params Descriptions
`message` tool params:


# 发送图片消息
```json
{
    "action": "send_pic",
    "path": "xxxx.png"
}
```

# 发送文件
```json
{
    "action": "send_file",
    "path": "xxxx.png"
}
```

# 发送文本消息
```json
{
    "action": "send_text",
    "text": "text content"
}
```


## Quick Start

```bash
# Prefer python3, fallback to python
PYTHON_CMD=$(command -v python3 >/dev/null 2>&1 && echo python3 || echo python)
PYTHONW_CMD=$(command -v pythonw3 >/dev/null 2>&1 && echo pythonw || echo pythonw)

# Run Feishu interaction script (non-blocking on Windows)
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    $PYTHONW_CMD scripts/feishu_bot.py
else
    # On Unix-like systems, use background process
    $PYTHON_CMD scripts/feishu_bot.py &
fi
```
