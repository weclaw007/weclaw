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
        "requires": { "bins": ["python", "python3"], "env": ["LARK_APP_ID", "LARK_APP_SECRET"] },
      },
  }
---

# feishu

Use this skill to start and manage Feishu (Lark) bot, send messages through Feishu bot, and interact with Feishu Open API. This skill provides Feishu bot functionality including message receiving, replying, and bot operations via lark-oapi SDK.Use the `message` tool. No provider-specific `feishu` tool exposed to the agent.


## Params Descriptions
`message` tool params:

**重要提示：发送视频文件（如 .mp4、.mov、.avi、.mkv、.flv、.wmv、.webm 等视频格式）时，必须使用 `send_video`，绝对不要使用 `send_file`。`send_file` 仅用于发送非图片、非视频的普通文件（如文档、压缩包等）。**

# 发送图片消息（用于发送图片文件，如 .png、.jpg、.jpeg、.gif、.bmp 等图片格式）
```json
{
    "action": "send_pic",
    "path": "xxxx.png"
}
```

# 发送视频消息（用于发送视频文件，如 .mp4、.mov、.avi、.mkv、.flv、.wmv、.webm 等视频格式。注意：任何视频文件都必须使用此 action，不要使用 send_file）
```json
{
    "action": "send_video",
    "path": "xxxx.mp4"
}
```

# 发送普通文件（仅用于发送非图片、非视频的普通文件，如 .pdf、.docx、.xlsx、.zip、.txt 等。视频文件请使用 send_video，图片文件请使用 send_pic）
```json
{
    "action": "send_file",
    "path": "xxxx.pdf"
}
```

# 发送文本消息（用于发送纯文本内容）
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
