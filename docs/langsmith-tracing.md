# LangSmith Tracing 使用指南

## 简介

[LangSmith](https://smith.langchain.com) 是 LangChain 官方提供的**可观测性平台**，专为 LLM 应用设计。它能够自动追踪每一次对话的完整执行链路，包括：

- 🤖 大模型的每次调用（输入 prompt、输出回复、token 用量、耗时）
- 🔧 工具调用的详细过程（调用参数、返回结果）
- 🔗 多轮对话的完整上下文
- ⚠️ 错误与异常的精确定位

**最大的优势是：零代码侵入，只需配置环境变量即可生效。**

由于本项目基于 LangChain + LangGraph 构建，LangSmith 可以自动捕获所有调用链路，无需在代码中添加任何额外的追踪逻辑。

---

## 快速配置

### 1. 获取 API Key

1. 访问 [LangSmith 官网](https://smith.langchain.com) 并注册/登录
2. 进入 **Settings** → **API Keys**
3. 点击 **Create API Key**，复制生成的 Key

### 2. 配置环境变量

在项目根目录的 `.env` 文件中添加以下 4 个变量：

```dotenv
# ── LangSmith 追踪配置 ──
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=lsv2_pt_your_api_key_here
LANGSMITH_PROJECT=your-project-name
```

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `LANGSMITH_TRACING` | 开关，设为 `true` 启用追踪 | `true` |
| `LANGSMITH_ENDPOINT` | LangSmith API 地址，通常无需修改 | `https://api.smith.langchain.com` |
| `LANGSMITH_API_KEY` | 你的 API Key | `lsv2_pt_xxxx` |
| `LANGSMITH_PROJECT` | 项目名称，用于在 LangSmith 中区分不同项目 | `my-chatbot` |

**就这么简单！** 配置完成后启动应用，所有对话请求将自动上报到 LangSmith。

### 3. 关闭追踪

如果需要临时关闭追踪，只需将 `LANGSMITH_TRACING` 改为 `false`：

```dotenv
LANGSMITH_TRACING=false
```

---

## 查看 Tracing 页面

### 进入项目

1. 登录 [LangSmith](https://smith.langchain.com)
2. 在左侧导航栏点击 **Projects**
3. 找到你配置的项目名称（对应 `LANGSMITH_PROJECT` 的值），点击进入

### 查看请求列表

进入项目后，你会看到 **Runs** 列表，每一行代表一次完整的对话请求：

```
┌─────────────────────────────────────────────────────────────────────┐
│  Projects > my-chatbot                                              │
├─────────────────────────────────────────────────────────────────────┤
│  Name            │ Status  │ Latency │ Tokens │ Time               │
│─────────────────────────────────────────────────────────────────────│
│  ▶ RunnableSeq.. │ ✅ OK   │ 3.2s    │ 1,245  │ 2 min ago          │
│  ▶ RunnableSeq.. │ ✅ OK   │ 8.7s    │ 3,891  │ 15 min ago         │
│  ▶ RunnableSeq.. │ ❌ Error│ 1.1s    │ 432    │ 1 hour ago         │
└─────────────────────────────────────────────────────────────────────┘
```

### 示例：查看一次完整对话的 Trace 详情

![trace页面](https://raw.githubusercontent.com/kkbig509/weclaw/main/langsmith-tracing.png "trace页面")

以下以一个真实的请求为例：用户发送了 "**今天最新的军事新闻**"，Agent 自动完成了意图识别 → 读取技能描述 → 调用搜索工具 → 汇总回复的完整流程。

点击该条 Run 进入详情页，左侧展示的是**瀑布图（Waterfall）**视图：

```
� LangGraph（0.00s）
│
├── 🤖 model / ChatOpenAI（17.54s）         ← 第一次大模型调用（意图识别 + 决策）
│
├── 🔧 tools（0.01s）
│   └── read_skill（0.00s）                  ← 读取 websearch 技能描述
│
├── 🤖 model / ChatOpenAI（10.73s）         ← 第二次大模型调用（生成工具调用命令）
│
├── 🔧 tools（28.35s）
│   └── run_command（28.34s）                ← 执行 mcp_client 搜索命令（耗时最长）
│
├── 🤖 model / ChatOpenAI（0.00s）          ← 第三次大模型调用（汇总结果生成最终回复）
│
└── 总耗时约 52s
```

#### 右侧详情面板

点击瀑布图中的任意节点，右侧会展开**详情面板**。以上图中选中的 `run_command` 节点为例：

**Input 标签页** — 显示工具收到的完整输入参数：

```json
{
  "input": "{\"command\": \"PYTHON_CMD=$(command -v python3 >/dev/null 2>&1 && echo python3 || echo python) && $PYTHON_CMD -m weclaw.agent.mcp_client -u https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/sse -k DASHSCOPE_API_KEY call_command bailian_web_search -a '{\"query\": \"今天最新的军事新闻\", \"count\": 5}'\"}"
}
```

**Output 标签页** — 显示工具返回的完整结果（JSON 格式），包含搜索到的新闻内容：

```json
{
  "output": {
    "additional_kwargs": {},
    "content": "{\"status\": 0, \"pages\": [{\"snippet\": \"军事领域动态复杂，事件可能迅速改变全球安全格局...\"}]}"
  }
}
```

**详情面板共有三个标签页：**

| 标签页 | 内容 |
|--------|------|
| **Input** | 该步骤收到的完整输入（如工具的调用命令、发送给大模型的 messages） |
| **Output** | 该步骤的完整输出（如工具返回的 JSON 结果、大模型生成的文本） |
| **Metadata** | 元数据，如模型名称、temperature、token 用量、运行耗时等 |

> 💡 **提示**：在右上角可以切换 **JSON** / **RAW** 视图模式查看数据，也可以点击复制按钮快速拷贝内容。

#### 瀑布图操作

在 Trace 详情页顶部，你可以使用以下工具栏功能：

- **列表 / Waterfall 视图切换**：默认使用 Waterfall 瀑布图，也可以切换为列表视图
- **Reset**：重置缩放和视图位置
- **� 缩放**：放大/缩小瀑布图，查看耗时分布细节
- **时间轴**：顶部的时间刻度（2s、7s、12s...52s）清晰展示每个步骤的耗时占比

#### 关键信息一目了然

通过瀑布图，你可以快速了解：

- **各步骤耗时占比**：一眼看出瓶颈在哪（如本例中 `run_command` 耗时 28.34s 占了大部分时间）
- **调用链路**：清晰看到 Agent 的决策过程（model → tools → model → tools → model）
- **状态**：成功的节点正常显示，失败的节点会以红色标记
- **嵌套结构**：tools 节点可展开/折叠查看具体的工具调用

---

## 实用技巧

### 1. 筛选与搜索

在 Runs 列表页，你可以使用顶部的筛选栏快速定位：

- **按状态筛选**：只看失败的请求（`Status = Error`）
- **按时间范围**：查看某个时间段内的请求
- **按 Latency 排序**：找出最慢的请求进行优化

### 2. 对比不同模型

如果你切换了不同的大模型（如从 `qwen-plus` 切换到 `gpt-4o`），可以在 LangSmith 中对比两者的：
- 响应质量
- 响应速度
- Token 消耗

### 3. 调试工具调用

当工具调用出现异常时，展开对应的 Tool 节点即可看到：
- 传入的参数是否正确
- 返回的原始结果是什么
- 是否有异常堆栈信息

### 4. 多轮对话追踪

对于多轮对话，每轮都会产生一条独立的 Trace。你可以通过 **Thread ID** 将同一会话的多轮对话关联起来查看。

---

## 常见问题

### Q: 配置了环境变量但看不到数据？

**A**: 请检查以下几点：
1. `LANGSMITH_TRACING` 是否设置为 `true`（注意是字符串 `true`，不是 `True` 或 `1`）
2. `LANGSMITH_API_KEY` 是否正确，可以在 LangSmith 网站上重新生成
3. 网络是否能正常访问 `https://api.smith.langchain.com`
4. 应用是否在修改 `.env` 后重新启动

### Q: 追踪数据会影响应用性能吗？

**A**: LangSmith 的追踪上报是**异步且非阻塞**的，对应用正常运行几乎没有影响。即使 LangSmith 服务暂时不可用，也不会导致应用报错。

### Q: 免费版有什么限制？

**A**: LangSmith 提供免费套餐，包含：
- 每月 5,000 次免费 Trace
- 14 天数据保留
- 对于个人开发和调试阶段完全够用

### Q: 如何保护敏感信息？

**A**: 如果对话中涉及敏感数据，可以考虑：
- 使用 LangSmith 的数据脱敏功能
- 在生产环境关闭追踪（`LANGSMITH_TRACING=false`）
- 使用自托管版本的 LangSmith
