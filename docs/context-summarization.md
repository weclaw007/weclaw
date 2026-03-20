# 历史消息压缩方案：summarize_and_rebuild_messages

## 背景

在长对话场景中，消息列表会随着轮次增加不断膨胀，最终超出 LLM 的上下文窗口限制（Context Window）。为了在不丢失关键信息的前提下控制 token 消耗，项目实现了基于摘要的历史消息压缩方案。

核心函数位于：`src/weclaw/utils/context_optimizer.py`

---

## 核心函数

```python
async def summarize_and_rebuild_messages(
    messages: list,
    summary_llm,
    max_token_limit: int = 10000,
    keep_recent_rounds: int = 6,
) -> tuple[list, list, SystemMessage | None] | None:
```

### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `messages` | `list` | — | 从 Agent state 中获取的完整消息列表 |
| `summary_llm` | LLM 实例 | — | 用于生成摘要的轻量模型 |
| `max_token_limit` | `int` | `10000` | 触发压缩的 token 阈值 |
| `keep_recent_rounds` | `int` | `6` | 保留最近几轮完整对话不压缩 |

### 返回值

- 不需要压缩时返回 `None`
- 需要压缩时返回三元组 `(all_removals, recent_messages_flat, summary_msg)`：
  - `all_removals`：需要从 state 中删除的 `RemoveMessage` 列表
  - `recent_messages_flat`：需要重新写入 state 的近期消息列表
  - `summary_msg`：新生成的摘要 `SystemMessage`

---

## 压缩流程

```
┌─────────────────────────────────────────────────────────────┐
│                     完整消息列表 messages                    │
└──────────────────────────┬──────────────────────────────────┘
                           │
                    估算 token 数
                    (字符数 ÷ 2)
                           │
              ┌────────────▼────────────┐
              │  token ≤ max_token_limit │──── 不压缩，返回 None
              └────────────┬────────────┘
                           │ token 超限
                           ▼
          ┌────────────────────────────────┐
          │  Step 1: 分离消息类型           │
          │  - system_prompt_messages      │  ← 纯系统提示词（保留）
          │  - old_summary_messages        │  ← 旧摘要 SystemMessage（删除）
          │  - non_system_messages         │  ← 对话消息（待切分）
          └────────────────┬───────────────┘
                           │
                           ▼
          ┌────────────────────────────────┐
          │  Step 2: 按完整轮次切分         │
          │  split_into_rounds()           │
          │  每轮以 HumanMessage 开头       │
          └────────────────┬───────────────┘
                           │
                           ▼
          ┌────────────────────────────────┐
          │  Step 3: 切分旧轮次 / 近期轮次  │
          │  old_rounds   = rounds[:-N]    │
          │  recent_rounds = rounds[-N:]   │  N = keep_recent_rounds
          └────────────────┬───────────────┘
                           │
                           ▼
          ┌────────────────────────────────┐
          │  Step 4: 序列化旧消息为纯文本   │
          │  serialize_messages_to_text()  │
          │  + 拼接旧摘要文本（若存在）     │
          └────────────────┬───────────────┘
                           │
                           ▼
          ┌────────────────────────────────┐
          │  Step 5: 调用摘要模型生成摘要   │
          │  summary_llm.ainvoke(...)      │
          └────────────────┬───────────────┘
                           │
                           ▼
          ┌────────────────────────────────┐
          │  Step 6: 构建返回结果           │
          │  - all_removals (RemoveMessage)│
          │  - recent_messages_flat        │
          │  - summary_msg (SystemMessage) │
          └────────────────────────────────┘
```

---

## 关键设计决策

### 1. Token 估算策略

使用字符数粗估，避免额外的 tokenizer API 调用：

```python
estimated_tokens = total_chars // 2
# 中文约 1.5 字符/token，英文约 4 字符/token，取保守值 2 字符/token
```

### 2. 完整轮次切分（split_into_rounds）

压缩的最小单位是**完整的对话轮次**，而非单条消息。这样可以避免将一轮对话中的 `HumanMessage`、`AIMessage`、`ToolMessage` 截断，确保摘要的语义完整性。

```
一轮 = HumanMessage + AIMessage(可能含 tool_calls) + ToolMessage(s) + AIMessage(最终回复)
```

`SystemMessage` 会被单独提取，不参与轮次切分。

### 3. 旧摘要的累积处理

如果 state 中已存在上一次压缩生成的摘要 `SystemMessage`（通过 `SUMMARY_MARKER` 标记识别），其文本内容会被**合并到本次摘要的输入**中，确保历史信息不会因多次压缩而丢失：

```python
old_summary_text = "\n".join(old_summary_messages 的内容) + "\n\n"
conversation_text = old_summary_text + serialize_messages_to_text(old_messages_flat)
```

### 4. 摘要消息的标记

生成的摘要 `SystemMessage` 使用固定前缀标记，便于下次压缩时识别和替换：

```python
SUMMARY_MARKER = "[Summary of previous conversation]"
summary_msg = SystemMessage(content=f"{SUMMARY_MARKER}\n{summary_text}")
```

### 5. 消息序列化（serialize_messages_to_text）

旧消息在传给摘要模型前，会被序列化为可读纯文本，避免将原始 Message 对象直接传入导致 API 报错：

```
[User]: 用户的问题
[Assistant]: AI 的回复 (called tools: tool_name({args}))
[Tool Result (tool_name)]: 工具返回结果（超过 500 字符时截断）
[System]: 系统消息内容
```

---

## 调用方式（Agent 侧）

在 Agent 的 `_summarize_if_needed` 方法中调用：

```python
result = await summarize_and_rebuild_messages(
    messages=messages,
    summary_llm=self._summary_llm,
    max_token_limit=self._max_token_limit,
    keep_recent_rounds=6,
)

if result is not None:
    all_removals, recent_messages_flat, summary_msg = result
    await self.agent.aupdate_state(
        self.config,
        {
            "messages": all_removals
            + [summary_msg]
            + recent_messages_flat
        },
    )
```

> **注意**：`aupdate_state` 中消息的写入顺序决定了最终在 state 中的位置。
> 先写入 `RemoveMessage`（删除旧消息），再写入 `summary_msg` 和 `recent_messages_flat`，
> 可确保摘要消息出现在近期消息之前。

---

## 压缩前后对比

**压缩前（state 中的消息）：**

```
SystemMessage (系统提示词)
SystemMessage [Summary of previous conversation] (旧摘要，若存在)
HumanMessage  (第 1 轮)
AIMessage
ToolMessage
AIMessage
HumanMessage  (第 2 轮)
...
HumanMessage  (第 N-5 轮，旧轮次开始)
...
HumanMessage  (第 N-4 轮，近期轮次开始)
...
HumanMessage  (第 N 轮，最新)
AIMessage
```

**压缩后（state 中的消息）：**

```
SystemMessage (系统提示词，保持不变)
SystemMessage [Summary of previous conversation] (新摘要，包含旧摘要+旧轮次内容)
HumanMessage  (第 N-4 轮，近期轮次开始)
...
HumanMessage  (第 N 轮，最新)
AIMessage
```

---

## 相关常量

| 常量 | 值 | 说明 |
|------|----|------|
| `SUMMARY_MARKER` | `"[Summary of previous conversation]"` | 摘要消息的识别前缀 |
| `SUMMARY_TIMEOUT` | `30` | 摘要请求超时时间（秒） |
| `TOOL_ARCHIVE_MIN_LENGTH` | `500` | 工具结果归档的内容长度阈值 |

---

## 相关模块

- `context_optimizer.py` — 本方案的核心实现
- `agent.py` — Agent 调用入口（`_summarize_if_needed`）
- `model_registry.py` — 摘要模型的注册与创建（`summary_model` 配置项）
