---
name: download
description: Download files from URLs to local paths using curl.
homepage: https://curl.se/docs/manpage.html
metadata:
  {
    "openclaw":
      {
        "emoji": "⬇️",
        "requires": { "bins": ["curl"] }
      },
  }
---

# download

Use `curl` to download remote files to local storage.

## Quick Start

```bash
# Download with original filename
curl -fL -O "https://example.com/file.zip"

# Download to a specific path
curl -fL "https://example.com/file.zip" -o "/path/to/file.zip"
```

## Common Options

```bash
# Resume interrupted download
curl -fL -C - "https://example.com/file.zip" -o "/path/to/file.zip"

# Add timeout (seconds)
curl -fL --connect-timeout 10 --max-time 600 "https://example.com/file.zip" -o "/path/to/file.zip"

# Use custom header (e.g. token)
curl -fL -H "Authorization: Bearer <TOKEN>" "https://example.com/private.bin" -o "./private.bin"
```

Notes:
- Use `-f` to fail on HTTP errors.
- Use `-L` to follow redirects.
- Prefer absolute output paths for predictable results.
