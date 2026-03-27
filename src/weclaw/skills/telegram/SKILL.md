---
name: telegram
description: Use this skill to start and manage Telegram bot, send messages through Telegram bot, and interact with Telegram API. This skill provides Telegram bot functionality including message sending, contact management, and bot operations.
homepage: local
metadata:
  {
    "openclaw":
      {
        "emoji": "🤖",
        "primaryEnv": "TELEGRAM_BOT_TOKEN",
        "requires": { "bins": ["python", "python3"] }
      },
  }
---

# telegram

Use this skill to start and manage Telegram bot, send messages through Telegram bot, and interact with Telegram API. This skill provides Telegram bot functionality including message sending, contact management, and bot operations.


## Quick Start

Telegram 适配器已集成到主程序中，通过 `TelegramAdapter` 启动：

```bash
# 设置环境变量
export TELEGRAM_BOT_TOKEN="your_bot_token"

# 启动 Telegram 适配器
weclaw start --adapter telegram
```