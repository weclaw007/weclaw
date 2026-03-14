---
name: browser
description: Open URLs, localhost pages, or local HTML files in the system default browser.
homepage: https://developer.apple.com/library/archive/documentation/Darwin/Reference/ManPages/man1/open.1.html
metadata:
  {
    "openclaw":
      {
        "emoji": "🌐",
        "requires": { "bins": ["open"] }
      },
  }
---

# browser

Use this skill to open web pages in your default browser.

## Quick Start

```bash
# Open a local development server
open http://localhost:3000

# Open a local HTML file
open /path/to/index.html
```

## Cross-platform

```bash
# macOS
open <url-or-file>

# Linux
xdg-open <url-or-file>

# Windows (PowerShell)
start <url-or-file>
```

## Common Use Cases

- Open `http://localhost:3000` / `http://127.0.0.1:8000`
- Open generated reports like `/tmp/report.html`
- Quickly preview static files in browser

Notes:
- Prefer `http://localhost:<port>` when a local server is running.
- For file preview, use absolute paths to avoid path confusion.
