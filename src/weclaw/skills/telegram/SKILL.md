---
name: telegram
description: Use this skill to start and manage Telegram bot, send messages through Telegram bot, and interact with Telegram API. This skill provides Telegram bot functionality including message sending, contact management, and bot operations.
homepage: local
metadata:
  {
    "openclaw":
      {
        "emoji": "🤖",
        "requires": { "bins": ["python", "python3"] }
      },
  }
---

# telegram

Use this skill to start and manage Telegram bot, send messages through Telegram bot, and interact with Telegram API. This skill provides Telegram bot functionality including message sending, contact management, and bot operations.


## Quick Start

```bash
# Prefer python3, fallback to python
PYTHON_CMD=$(command -v python3 >/dev/null 2>&1 && echo python3 || echo python)
PYTHONW_CMD=$(command -v pythonw3 >/dev/null 2>&1 && echo pythonw || echo pythonw)

# Run Telegram interaction script (non-blocking on Windows)
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    $PYTHONW_CMD scripts/telegram.py
else
    # On Unix-like systems, use background process
    $PYTHON_CMD scripts/telegram.py &
fi
```