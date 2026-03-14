---
name: wechat
description: Use this skill to send WeChat messages, manage contacts, and interact with WeChat. This is the primary skill for sending messages through WeChat, including sending text messages to contacts or groups, viewing contact information, and managing WeChat moments.
homepage: local
metadata:
  {
    "openclaw":
      {
        "emoji": "💬",
        "requires": { "bins": ["python", "python3"] }
      },
  }
---

# wechat

Use this skill to send WeChat messages, manage contacts, and interact with WeChat. This is the primary skill for sending messages through WeChat, including sending text messages to contacts or groups, viewing contact information, and managing WeChat moments.  Use the `message` tool. No provider-specific `wechat` tool exposed to the agent.

## Features

- **Send WeChat messages** - Send text messages to contacts or groups (发信息/发送消息)
- **Message sending capability** - Primary function for sending WeChat messages
- View and manage contact list
- Browse and post moments (朋友圈)
- Auto-reply functionality
- Message scheduling

**Core Function**: Send WeChat messages to specific contacts or groups when users request to "send a message" or "发信息" through WeChat.

## Params Descriptions
`message` tool params:

### Get Self Information (获取个人信息)
Get personal WeChat information such as username, nickname, etc. Use when user asks about their own WeChat info.

```json
{
    "action": "get_self_info"
}
```

### Search Contact Information (搜索联系人)
Search contact information based on specified key, typically used to query user's username. Use when user wants to find a contact by name or nickname.

```json
{
    "action": "search_contact",
    "key": "nickname"
}
```

### Send Message to Friend/Group (发送消息给好友/群组)
**Primary function for sending WeChat messages**. Send chat message to friend or group. Use when user requests to "send a message", "发信息", or "用微信发消息".

```json
{
    "action": "send_message",
    "username": "wxid_xx",
    "message": "message content"
}
```

## Quick Start

```bash
# Prefer python3, fallback to python
PYTHON_CMD=$(command -v python3 >/dev/null 2>&1 && echo python3 || echo python)
PYTHONW_CMD=$(command -v pythonw3 >/dev/null 2>&1 && echo pythonw || echo pythonw)

# Run WeChat interaction script (non-blocking on Windows)
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    $PYTHONW_CMD scripts/main.py
else
    # On Unix-like systems, use background process
    $PYTHON_CMD scripts/main.py &
fi
```
