# MCP 技能开发指南

> 只需 3 步，5 分钟，零代码接入任何 MCP 服务。

Weclaw 内置了完整的 MCP（Model Context Protocol）客户端框架。你只需要编写一个 `SKILL.md` 描述文件，就能将任何标准 MCP 服务器接入到你的 AI 助手中——**无需编写任何 Python 代码**。

## 工作原理

```
用户提问 → Agent 识别意图 → 读取 SKILL.md → 调用 weclaw.agent.mcp_client 模块 → 连接 MCP 服务器 → 返回结果
```

- **Agent** 根据 `SKILL.md` 的 `description` 字段判断何时使用该技能
- **weclaw.agent.mcp_client** 是内置的通用 MCP 客户端模块，通过 SSE 协议连接远程 MCP 服务器
- 你不需要写任何胶水代码，所有通信由框架自动完成

## 快速开始：3 步添加 MCP 技能

### 第 1 步：创建技能目录

在 `src/weclaw/skills/` 下新建一个目录，目录名即为技能 ID：

```bash
mkdir -p src/weclaw/skills/my-skill
```

### 第 2 步：编写 SKILL.md

在技能目录下创建 `SKILL.md` 文件，包含 **front matter 元数据** 和 **Markdown 正文** 两部分。

#### 最小模板

```markdown
---
name: my-skill
description: 简短描述这个技能做什么，Agent 靠这段描述决定何时使用它。使用 weclaw.agent.mcp_client 模块调用。
homepage: https://your-mcp-server-url/sse
metadata:
  {
    "openclaw":
      {
        "emoji": "🔧",
        "primaryEnv": "YOUR_API_KEY",
        "requires": { "bins": ["python"] }
      },
  }
---

# My Skill

技能的详细说明。

## Supported Commands

### 1. `command_name`
工具的功能描述。
- **param1** (string, 必填): 参数说明
- **param2** (string, 可选): 参数说明

## Quick Start

Python command compatibility:

\```bash
PYTHON_CMD=$(command -v python3 >/dev/null 2>&1 && echo python3 || echo python)
\```

调用示例（`-k` 传入的是环境变量名，程序会自动读取环境变量的值；`-a` 使用 JSON 格式传入参数；`-H` 可传入自定义 HTTP 头，每个 header 需单独 `-H` 指定）：

\```bash
$PYTHON_CMD -m weclaw.agent.mcp_client \
  -u https://your-mcp-server-url/sse \
  -k YOUR_API_KEY \
  -H 'X-Custom-Header=value' \
  -H 'X-Another=value2' \
  call_command command_name -a '{"param1": "value", "param2": "value2"}'
\```

## Notes

- 需要 YOUR_API_KEY 环境变量
- **无需安装任何额外 Python 包，直接使用 `python -m weclaw.agent.mcp_client` 即可**
```

### 第 3 步：配置环境变量

在项目根目录的 `.env` 文件中添加 MCP 服务所需的 API Key：

```bash
# 你的 MCP 服务 API Key
YOUR_API_KEY=your-key-here
```

**完成！** 重启 Weclaw，新技能会被自动发现并加载。

## SKILL.md 字段详解

### Front Matter（必填）

| 字段 | 说明 | 示例 |
|------|------|------|
| `name` | 技能名称，需与目录名一致 | `amap` |
| `description` | 技能功能描述，**Agent 根据这个字段决定何时调用技能**，建议详细描述。末尾需包含"使用 weclaw.agent.mcp_client 模块调用" | `高德地图地理信息服务...使用 weclaw.agent.mcp_client 模块调用。` |
| `homepage(可选)` | MCP 服务器的 SSE 端点 URL | `https://dashscope.aliyuncs.com/api/v1/mcps/amap-maps/sse` |
| `metadata.openclaw.emoji` | 技能图标 emoji | `🗺️` |
| `metadata.openclaw.primaryEnv` | 主要环境变量名，`-k` 参数传入此名称，程序自动读取其值 | `DASHSCOPE_API_KEY` |
| `metadata.openclaw.requires.bins` | 运行依赖的命令行工具 | `["python"]` |
| `metadata.openclaw.os`（可选） | 限制操作系统，不填则全平台 | `["darwin", "linux"]` |

### Markdown 正文（建议）

正文部分会在 Agent 调用技能时被读取，建议包含：

- **Available Commands**：列出所有可用工具及参数，帮助 Agent 正确调用
- **Quick Start**：命令行调用示例
- **Notes**：注意事项

> 💡 **关键提示**：`description` 字段的质量直接影响 Agent 能否正确识别和使用该技能。描述越准确详细，Agent 越聪明。

## 实战示例

### 示例 1：WebSearch 网页搜索（最简技能）

```
src/weclaw/skills/websearch/
└── SKILL.md          ← 只需这一个文件！
```

```yaml
---
name: websearch
description: 网页搜索服务，支持增强意图识别的网页搜索。返回 AI 优化的结果。使用 weclaw.agent.mcp_client 模块调用。
homepage: https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/sse
metadata:
  { "openclaw": { "emoji": "🔍", "primaryEnv": "DASHSCOPE_API_KEY", "requires": { "bins": ["python"] } } }
---
```

只需一个 `SKILL.md` 文件，包含 front matter 和工具说明，就完成了一个完整的 MCP 技能接入。

### 示例 2：AMap 高德地图（功能丰富的技能）

```
src/weclaw/skills/amap/
└── SKILL.md          ← 同样只需这一个文件
```

高德地图技能包含 15 个工具（地理编码、天气查询、路线规划等），但接入方式完全相同——只是 `SKILL.md` 中列出了更多工具和参数说明。

## 调试技巧

### 查看可用工具列表

不确定 MCP 服务器提供了哪些工具？使用 `list-tools` 命令查看：

```bash
python -m weclaw.agent.mcp_client \
  -u https://your-mcp-server-url/sse \
  -k YOUR_API_KEY \
  list-tools
```

### 手动测试工具调用

```bash
python -m weclaw.agent.mcp_client \
  -u https://your-mcp-server-url/sse \
  -k YOUR_API_KEY \
  call_command command_name -a '{"param": "value"}'
```

### 传入自定义 HTTP 头

某些 MCP 服务器可能需要额外的 HTTP 头（如自定义认证、租户标识等），使用 `-H`/`--header` 参数：

```bash
python -m weclaw.agent.mcp_client \
  -u https://your-mcp-server-url/sse \
  -k YOUR_API_KEY \
  -H 'X-Tenant-Id=my-tenant' \
  -H 'X-Custom=value' \
  call_command command_name -a '{"param": "value"}'
```

> **注意**：自定义 header 可以覆盖默认的 `Authorization` 头。如果你的 MCP 服务器使用非 Bearer 的认证方式，可以通过 `-H 'Authorization=Basic xxx'` 来覆盖。

> **参数格式说明**：
> - **`-a` 工具参数**：使用 JSON 格式传入，如 `-a '{"city": "北京", "count": 5}'`。
> - **`-H` 自定义 HTTP 头**，格式为 key=value，每个 header 需单独 `-H` 指定。如 `-H 'X-Token=abc' -H 'X-Org=myorg'`

### 查看已加载的技能

启动 Weclaw 后，在 Web 界面中可以查看所有已加载的技能列表和启用状态。

## 接入 DashScope MCP 服务

[阿里云百炼](https://bailian.console.aliyun.com/) 提供了多个开箱即用的 MCP 服务，只需一个 `DASHSCOPE_API_KEY` 即可使用：

| 服务 | SSE 端点 |
|------|----------|
| 高德地图 | `https://dashscope.aliyuncs.com/api/v1/mcps/amap-maps/sse` |
| 网页搜索 | `https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/sse` |

更多 DashScope MCP 服务请参阅 [阿里云百炼文档](https://help.aliyun.com/zh/model-studio/)。

## 常见问题

### Q: 必须用 DashScope 吗？
**A**: 不是。Weclaw 的 MCP 客户端支持任何符合 MCP 标准的 SSE 服务器。只需将 `homepage` 指向你的 MCP 服务器 URL 即可。

### Q: 需要安装额外的 Python 包吗？
**A**: 不需要。`weclaw.agent.mcp_client` 模块使用的 `mcp` 库已包含在项目依赖中，开箱即用。

### Q: 如何获取 MCP 服务器提供的工具列表？
**A**: 使用 `python -m weclaw.agent.mcp_client -u <URL> -k <ENV_VAR_NAME> list-tools` 命令即可列出所有可用工具及其参数。`-k` 传入环境变量名（如 `DASHSCOPE_API_KEY`），程序会自动读取环境变量的值。

### Q: 如何传入自定义 HTTP 头？
**A**: 使用 `-H` 或 `--header` 参数，格式为 `key=value`，每个 header 需单独 `-H` 指定。例如：`'-H 'X-Tenant-Id=my-tenant' -H 'X-Custom=value'`。自定义 header 会合并到默认 headers 中，也可以覆盖默认的 `Authorization` 头。

### Q: 技能没有被 Agent 识别怎么办？
**A**: 检查以下几点：
1. `SKILL.md` 文件是否放在 `src/weclaw/skills/<skill-name>/SKILL.md` 路径下
2. front matter 格式是否正确（以 `---` 开头和结尾）
3. `description` 字段是否足够描述技能的用途
4. 重启 Weclaw 使新技能生效
