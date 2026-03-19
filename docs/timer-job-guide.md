# 定时任务使用指南

Weclaw 内置了定时任务功能，你可以通过自然语言告诉 AI 助手"X 分钟后提醒我做某事"，AI 会自动创建定时任务，到期后主动推送提醒消息。

## 功能特性

- 🎯 **精准触发**：基于 APScheduler AsyncIOScheduler，毫秒级精度，无轮询开销
- 💾 **持久化存储**：任务写入 SQLite 数据库，重启后自动恢复
- 🔄 **重启恢复**：服务重启时自动加载所有 pending 任务，已过期的立即触发，未过期的重建调度
- 🗂️ **Session 隔离**：每个 WebSocket 连接拥有独立的任务数据库，互不干扰
- 🤖 **大模型处理**：任务到期后由大模型决定如何响应，支持调用其他工具（如查天气、发消息等）
- 🔁 **重复任务**：支持按固定间隔重复触发，可设置最大重复次数或无限循环
---

## 快速上手

直接用自然语言与 AI 对话即可，无需了解底层细节：

**一次性提醒**

```
用户: 1分钟后提醒我喝水
AI:   好的，已为你设置 1 分钟后的提醒 ✅

（1分钟后，AI 主动推送）
AI:   ⏰ 提醒：该喝水了！
```

```
用户: 明天上午9点提醒我开周会
AI:   好的，已设置 2026-03-20T09:00:00 的提醒

用户: 取消刚才的提醒
AI:   已取消该定时任务
```

**重复任务**

```
用户: 每隔1分钟帮我查一次北京的天气，查10次就好
AI:   好的，已设置每 60 秒重复查询北京天气，最多执行 10 次 ✅

（每分钟触发一次）
AI:   ⏰ 北京当前天气：晴，气温 15°C 🌤️
```

```
用户: 每小时提醒我喝水，一直提醒
AI:   好的，已设置每小时提醒喝水（无限循环）✅

用户: 停止那个喝水提醒
AI:   已取消该定时任务
```

---

## 支持的操作

AI 助手通过内置的 `timer_job` 工具管理定时任务，支持以下操作：

### 创建任务

**方式一：相对时间（推荐）**

告诉 AI "X 分钟/小时/秒后"，AI 会自动换算为 `interval` 参数（秒数）：

| 用户说 | AI 传入参数 |
|--------|------------|
| 1分钟后提醒我 | `interval=60` |
| 2小时后提醒我 | `interval=7200` |
| 30秒后执行 | `interval=30` |

**方式二：绝对时间**

告诉 AI 具体时间点，AI 会传入 `fire_time` 参数（ISO 8601 本地时间）：

| 用户说 | AI 传入参数 |
|--------|------------|
| 明天上午9点提醒我 | `fire_time="2026-03-20T09:00:00"` |
| 下午3点半开会 | `fire_time="2026-03-19T15:30:00"` |

**方式三：重复任务**

在以上两种方式的基础上，额外告诉 AI 重复间隔和次数，AI 会附加 `repeat_interval` 和 `max_repeat` 参数：

| 用户说 | AI 传入参数 |
|--------|------------|
| 每分钟查一次天气，查10次 | `interval=60, repeat_interval=60, max_repeat=10` |
| 每小时提醒喝水，一直提醒 | `interval=3600, repeat_interval=3600` |
| 每30秒检查一次，最多5次 | `interval=30, repeat_interval=30, max_repeat=5` |

> `repeat_interval` 为重复间隔秒数；`max_repeat` 为最大触发次数，不填则无限循环。

### 查询任务

```
用户: 我有哪些待执行的提醒？
用户: 查询刚才那个任务的状态
```

### 更新任务

```
用户: 把刚才的提醒改到下午4点
用户: 把那个提醒推迟30分钟
```

### 删除任务

```
用户: 取消所有提醒
用户: 删除那个开会提醒
用户: 停止那个每分钟查天气的任务
```

---

## 任务到期后的行为

任务到期时，系统会将任务描述作为 prompt 交给大模型处理，大模型可以：

- 直接回复提醒文字
- 调用其他工具（如查询天气、发送飞书/Telegram 消息等）
- 执行复杂的组合操作

**示例**：

```
# 创建时的描述
"查询北京今天的天气并告诉我"

# 到期后大模型会自动调用天气工具，然后推送结果
AI: ⏰ 北京今天天气：晴，气温 12~22°C，适合外出 🌤️
```

---

## 技术设计

### 架构概览

```
用户对话
  ↓
大模型调用 timer_job 工具
  ↓
JobScheduler.add_job()
  ├── 写入 SQLite（持久化）
  └── APScheduler 注册调度 job
        ├── 一次性任务 → DateTrigger
        └── 重复任务   → IntervalTrigger
              ↓（到期触发）
  _fire_job()
  ├── 一次性任务：标记 status = fired
  └── 重复任务：repeat_count+1
        ├── 未达 max_repeat → 保持 pending，继续触发
        └── 已达 max_repeat → 标记 status = fired，移除调度
              ↓
  调用 on_fire 回调
        ↓
  Client._handle_job_fire()
  └── agent.astream_text(描述) → WebSocket 流式推送
```

### 核心组件

| 组件 | 文件 | 职责 |
|------|------|------|
| `JobScheduler` | `src/weclaw/utils/job_scheduler.py` | 定时器管理、SQLite 持久化 |
| `timer_job` 工具 | `src/weclaw/agent/client.py` | 大模型调用接口、参数校验 |
| `_handle_job_fire` | `src/weclaw/agent/client.py` | 到期回调、流式推送 |

### 数据库结构

每个 session 对应一个独立的 SQLite 文件，存储在 `~/.weclaw/jobs/` 目录下：

```sql
CREATE TABLE jobs (
    job_id          TEXT PRIMARY KEY,       -- UUID
    fire_time       TEXT NOT NULL,          -- 下次触发时间（本地时间 ISO 8601）
    description     TEXT NOT NULL,          -- 任务描述（到期后交给大模型）
    status          TEXT NOT NULL,          -- pending / fired / cancelled
    created_at      TEXT NOT NULL,          -- 创建时间
    repeat_interval INTEGER DEFAULT NULL,   -- 重复间隔秒数（NULL 表示一次性任务）
    max_repeat      INTEGER DEFAULT NULL,   -- 最大重复次数（NULL 表示无限重复）
    repeat_count    INTEGER NOT NULL DEFAULT 0  -- 已触发次数
);
```

### 任务状态流转

**一次性任务**

```
pending  ──(到期触发)──→  fired
pending  ──(手动删除)──→  cancelled
```

**重复任务**

```
pending  ──(每次触发，repeat_count+1，未达 max_repeat)──→  pending（继续循环）
pending  ──(触发次数达到 max_repeat)────────────────────→  fired
pending  ──(手动删除)────────────────────────────────────→  cancelled
```

### 重启恢复机制

服务重启时，`JobScheduler.start()` 会自动：

1. 加载数据库中所有 `status = pending` 的任务（包括一次性和重复任务）
2. 对于 `fire_time` 已过期的任务 → **立即触发**（补偿执行）
3. 对于 `fire_time` 未到期的任务 → **重建 APScheduler 调度 job**
   - 一次性任务：重建 `DateTrigger`
   - 重复任务：重建 `IntervalTrigger`，从下次触发时间开始继续执行

### 时间处理

`fire_time` 统一使用**本地时间**（无时区信息），兼容以下格式：

| 格式 | 示例 | 处理方式 |
|------|------|---------|
| 本地时间（推荐） | `2026-03-19T12:30:00` | 直接使用 |
| 带 UTC 标记 | `2026-03-19T04:30:00Z` | 自动转换为本地时间 |
| 带时区偏移 | `2026-03-19T12:30:00+08:00` | 自动转换为本地时间 |

---

## 注意事项

1. **任务与 Session 绑定**：每个 WebSocket 连接有独立的任务库，断开连接后定时器会被取消，但数据库记录保留。重新连接后不会自动恢复上次 session 的任务（每次连接是全新 session）。

2. **服务必须保持运行**：定时任务依赖 Weclaw 服务进程，如果服务停止，定时器也会停止。重启后只有当前 session 的任务会被恢复。

3. **大模型处理时间**：任务到期后需要调用大模型生成响应，实际推送时间会比 `fire_time` 晚几秒。

4. **并发安全**：`JobScheduler` 基于 `asyncio` 单线程事件循环，天然线程安全，无需额外加锁。

5. **重复任务的 `fire_time` 含义**：对于重复任务，数据库中的 `fire_time` 字段记录的是**下次触发时间**，每次触发后会自动更新为下一次的预计触发时间。

6. **无限重复任务的停止**：`max_repeat` 为 `None` 时任务无限循环，只能通过手动删除（告诉 AI "取消/停止那个任务"）来终止。

