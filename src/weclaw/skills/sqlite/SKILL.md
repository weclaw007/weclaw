---
name: sqlite
description: Query and operate local SQLite .db files using the sqlcipher CLI (supports both encrypted and unencrypted databases).
homepage: https://www.zetetic.net/sqlcipher/sqlcipher-api/
metadata:
  {
    "openclaw":
      {
        "emoji": "🗃️",
        "requires": { "bins": ["sqlcipher"] },
        "install":
          [
            {
              "id": "sqlcipher",
              "kind": "brew",
              "formula": "sqlcipher",
              "bins": ["sqlcipher"],
              "label": "Install sqlcipher (Homebrew)",
            },
          ],
      },
  }
---

# sqlite

Use `sqlcipher` to inspect schema, query data, and execute update statements on a local `.db` file.

For encrypted databases, set key first:

```bash
sqlcipher /path/to/encrypted.db "PRAGMA key='YOUR_PASSWORD'; .tables"
```

## Quick Start

```bash
# List all tables
sqlcipher /path/to/app.db ".tables"

# Describe one table
sqlcipher /path/to/app.db ".schema users"

# Query data
sqlcipher -header -column /path/to/app.db "SELECT id, name FROM users LIMIT 20;"
```

## Write Operations

```bash
# Update rows
sqlcipher /path/to/app.db "UPDATE users SET active = 1 WHERE id = 1001;"

# Insert row
sqlcipher /path/to/app.db "INSERT INTO users(name, email) VALUES ('Alice', 'alice@example.com');"

# Delete row
sqlcipher /path/to/app.db "DELETE FROM users WHERE id = 1001;"
```

## Password Operations

Reset password for an already encrypted database (in-place `rekey`):

```bash
sqlcipher /path/to/encrypted.db "PRAGMA key='OLD_PASSWORD'; PRAGMA rekey='NEW_PASSWORD';"
```

Set a new password for an unencrypted database (backup first, then replace original name):

```bash
DB="/path/to/app.db"
BACKUP_DB="${DB}.bak"
ENC_DB="${DB}.enc"

cp "$DB" "$BACKUP_DB"

sqlcipher "$DB" "ATTACH DATABASE '$ENC_DB' AS encrypted KEY 'NEW_PASSWORD'; SELECT sqlcipher_export('encrypted'); DETACH DATABASE encrypted;"

mv "$ENC_DB" "$DB"
```

Remove password from an encrypted database (backup first, then replace original name):

```bash
DB="/path/to/app.db"
BACKUP_DB="${DB}.encrypted.bak"
DEC_DB="${DB}.dec"

cp "$DB" "$BACKUP_DB"

sqlcipher "$DB" "PRAGMA key='OLD_PASSWORD'; ATTACH DATABASE '$DEC_DB' AS plaintext KEY ''; SELECT sqlcipher_export('plaintext'); DETACH DATABASE plaintext;"

mv "$DEC_DB" "$DB"
```

Notes for password operations:
- For unencrypted databases, do not use `rekey` directly. Use `ATTACH ... KEY ...` + `sqlcipher_export(...)`.
- For password removal, export to plaintext database, then rename back to original file name.
- Verify with: `sqlcipher /path/to/db "PRAGMA key='PASSWORD'; .tables"`

Notes:
- For read tasks, prefer `-header -column` for readable output.
- `sqlcipher` can also open unencrypted SQLite databases directly.
- Exclude system tables when needed:
  `SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;`
