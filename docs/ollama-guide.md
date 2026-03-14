# Ollama 使用指南

Ollama 是一个轻量级的本地大模型运行框架，支持在个人电脑上运行开源大语言模型。Weclaw 内置了对 Ollama 的完整支持，可以自动发现并使用本地已安装的模型。

## 为什么选择 Ollama？

- **隐私保护**：所有数据在本地处理，不会发送到外部服务器
- **零成本**：无需 API Key，无调用费用
- **离线可用**：无需网络连接即可使用
- **丰富的模型生态**：支持 Llama、Qwen、Gemma、DeepSeek 等主流开源模型

## 安装 Ollama

### macOS

推荐使用官方安装包：

```bash
# 方式一：通过官网下载（推荐）
# 访问 https://ollama.com/download 下载 macOS 安装包

# 方式二：通过 Homebrew 安装
brew install ollama
```

### Linux

```bash
# 一键安装脚本
curl -fsSL https://ollama.com/install.sh | sh
```

### Windows

访问 [https://ollama.com/download](https://ollama.com/download) 下载 Windows 安装包并运行。

### 验证安装

安装完成后，在终端运行以下命令验证：

```bash
ollama --version
```

如果输出版本号（如 `0.6.2`），说明安装成功。

## 启动 Ollama 服务

Ollama 需要在后台运行一个服务进程来处理模型推理请求。

```bash
# 启动 Ollama 服务（默认监听 http://localhost:11434）
ollama serve
```

> 💡 **提示**：在 macOS 上，如果通过官方安装包安装，Ollama 会作为系统服务自动启动，无需手动运行 `ollama serve`。

确认服务运行状态：

```bash
# 检查服务是否正常响应
curl http://localhost:11434
# 应该返回 "Ollama is running"
```

## 下载模型

Ollama 支持数百种开源模型，以下是一些推荐的模型：

### 推荐模型

| 模型 | 命令 | 大小 | 说明 |
|------|------|------|------|
| Qwen3 8B | `ollama pull qwen3:8b` | ~5 GB | 通义千问，中英文能力强，推荐中文场景 |
| Qwen3 4B | `ollama pull qwen3:4b` | ~2.6 GB | 轻量版千问，适合低配机器 |
| Llama 3.2 3B | `ollama pull llama3.2:3b` | ~2 GB | Meta 出品，综合能力好，英文见长 |
| Gemma 3 4B | `ollama pull gemma3:4b` | ~3 GB | Google 出品，小巧且能力均衡 |
| DeepSeek-R1 8B | `ollama pull deepseek-r1:8b` | ~5 GB | DeepSeek 推理模型，擅长逻辑推理 |
| Phi-4 Mini | `ollama pull phi4-mini` | ~2.4 GB | 微软出品，小模型性能出众 |

### 下载模型

```bash
# 下载模型（以 Qwen3 8B 为例）
ollama pull qwen3:8b

# 下载进度会实时显示
# pulling manifest
# pulling 6e4c38e12d01... 100% ▕████████████████▏ 4.9 GB
# ...
# success
```

### 查看已下载的模型

```bash
ollama list
```

输出示例：

```
NAME                    ID              SIZE      MODIFIED
qwen3:8b                a]2b2d3ce3b1    4.9 GB    2 hours ago
llama3.2:3b             a80c4f17acd5    2.0 GB    3 days ago
gemma3:4b               a2af810d3bfa    3.3 GB    1 week ago
```

### 删除模型

```bash
# 删除不需要的模型以释放磁盘空间
ollama rm qwen3:8b
```

## 在 Weclaw 中使用 Ollama

### 自动发现

Weclaw 默认开启了 Ollama 模型自动发现功能。只要 Ollama 服务正在运行，启动 Weclaw 时会自动检测到本地已安装的模型，并以 `ollama/` 前缀注册到可用模型列表中。

例如，如果你本地安装了 `qwen3:8b`，它会显示为 `ollama/qwen3:8b`。

### 配置说明

在 `models.yaml` 中的 Ollama 相关配置：

```yaml
# Ollama 配置
ollama:
  # Ollama 服务地址（默认 http://localhost:11434）
  host: http://localhost:11434
  # 是否自动发现本地模型
  auto_discover: true
```

如果你的 Ollama 服务运行在非默认端口，修改 `host` 即可。

### 手动注册 Ollama 模型

如果不想使用自动发现，也可以在 `models.yaml` 中手动配置 Ollama 模型：

```yaml
models:
  my-qwen:
    provider: ollama
    model: qwen3:8b
    base_url: http://localhost:11434
```

### 在 UI 中使用

1. 确保 Ollama 服务已启动
2. 启动 Weclaw agent 和 server
3. 在 Web 页面顶部的模型下拉列表中选择以 `ollama/` 开头的模型
4. 如果刚安装了新模型，点击 🔄 按钮刷新列表

## 硬件要求

运行本地模型对硬件有一定要求，以下是建议配置：

| 模型参数量 | 最低内存 | 推荐内存 | 示例模型 |
|-----------|---------|---------|---------|
| 1B ~ 3B | 4 GB | 8 GB | llama3.2:1b, phi4-mini |
| 4B ~ 8B | 8 GB | 16 GB | qwen3:8b, llama3.1:8b |
| 14B ~ 32B | 16 GB | 32 GB | qwen3:14b, gemma3:27b |
| 70B+ | 64 GB | 128 GB | llama3.1:70b |

> ⚠️ **注意**：如果内存不足，模型加载会非常缓慢甚至失败。建议根据自己的硬件条件选择合适大小的模型。如果有 GPU（NVIDIA/Apple Silicon），推理速度会大幅提升。

## 常见问题

### Q: Ollama 服务启动失败？

```bash
# 查看是否有端口冲突
lsof -i :11434

# 指定其他端口启动
OLLAMA_HOST=0.0.0.0:11435 ollama serve
```

如果更换了端口，记得在 `models.yaml` 中修改 `ollama.host`。

### Q: 模型下载速度太慢？

Ollama 模型默认从官方服务器下载。如果网络环境不佳，可以尝试：

1. 使用代理

```bash
# 设置代理后再下载
export https_proxy=http://your-proxy:port
ollama pull qwen3:8b
```

### Q: Weclaw 中看不到 Ollama 模型？

请按顺序排查：

1. 确认 Ollama 已安装：`ollama --version`
2. 确认服务已启动：`curl http://localhost:11434`
3. 确认有已下载的模型：`ollama list`
4. 确认 `models.yaml` 中 `auto_discover` 为 `true`
5. 在 Weclaw UI 中点击 🔄 刷新模型列表

### Q: 本地模型回答质量不如云端模型？

这是正常现象。本地运行的开源模型（通常 8B 以下参数量）在能力上与 GPT-4o、Claude 等大型闭源模型有一定差距。建议：

- 对于简单任务（日常对话、文本处理），使用本地模型即可
- 对于复杂任务（代码生成、深度推理），切换到云端模型
- 选择针对特定任务优化的模型（如 DeepSeek-R1 擅长推理）

## 更多资源

- [Ollama 官网](https://ollama.com/)
- [Ollama GitHub](https://github.com/ollama/ollama)
- [Ollama 模型库](https://ollama.com/library) — 浏览所有可用模型
- [Ollama API 文档](https://github.com/ollama/ollama/blob/main/docs/api.md)
