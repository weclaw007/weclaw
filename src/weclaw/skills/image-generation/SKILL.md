---
name: image-generation
description: 图片生成服务，支持文生图和图片编辑。通义千问图像模型，擅长复杂中英文文本渲染。使用 weclaw.agent.mcp_client 模块调用 DashScope QwenImage MCP 服务。
homepage: https://dashscope.aliyuncs.com/api/v1/mcps/QwenImage/sse
metadata:
  {
    "openclaw":
      {
        "emoji": "🖼️",
        "primaryEnv": "DASHSCOPE_API_KEY",
        "requires": { "bins": ["python"] }
      },
  }
---

# image-generation (图片生成)

文本生成图片与图片编辑服务，支持多种艺术风格，擅长复杂中英文文本渲染。通过 `python -m weclaw.agent.mcp_client` 调用远程服务。

## Prerequisites

- DashScope API key from [阿里云百炼](https://bailian.console.aliyun.com/)
- `weclaw.agent.mcp_client` 模块已内置，无需安装任何额外依赖

## Supported Commands

### 1. `modelstudio_qwen_image_gen` - 文生图
通义千问文生图模型，支持多种艺术风格，擅长复杂中英文文本渲染。
- **prompt** (string, 必填): 正向提示词，描述期望生成图像的元素和视觉特点，超过 800 字符自动截断
- **negative_prompt** (string, 可选): 反向提示词，描述不希望出现的内容，超过 500 字符自动截断
- **size** (string, 可选): 输出图像分辨率，格式为 `宽*高`，默认 `1328*1328`
- **n** (integer, 可选): 生成图片数量，默认 1
- **prompt_extend** (boolean, 可选): 是否开启 prompt 智能改写，开启后使用大模型优化输入 prompt
- **watermark** (boolean, 可选): 是否添加水印，可设置为 true 或 false

### 2. `modelstudio_qwen_image_edit` - 图片编辑
支持精准的中英双语文字编辑、调色、细节增强、风格迁移、增删物体、改变位置和动作等操作。
- **image_url** (string, 必填): 输入图像的 URL 地址，需为公网可访问地址（HTTP/HTTPS）。格式：JPG/JPEG/PNG/BMP/TIFF/WEBP，分辨率 [384, 3072]，大小不超过 10MB，URL 不能包含中文字符
- **prompt** (string, 必填): 正向提示词，描述期望的编辑效果，超过 800 字符自动截断
- **negative_prompt** (string, 可选): 反向提示词，描述不希望出现的内容，超过 500 字符自动截断
- **watermark** (boolean, 可选): 是否添加水印，可设置为 true 或 false

## Quick Start

Python command compatibility (some machines use `python`, others use `python3`):

```bash
PYTHON_CMD=$(command -v python3 >/dev/null 2>&1 && echo python3 || echo python)
```

调用工具示例（以文生图为例）：

> **重要：`-u`（--base-url）和 `-k`（--api-key）是必填参数，每次调用都必须传递，不可省略。`-k` 传入的是环境变量名（而非变量值），程序会自动读取环境变量。**
>
> **参数格式：`-a` 支持 key=value 格式（推荐，跨平台兼容）和 JSON 格式，多个参数用空格分隔。如果值包含空格，需用双引号包裹，如 `-a prompt="A cinematic sunset"`。**

```bash
$PYTHON_CMD -m weclaw.agent.mcp_client \
  -u https://dashscope.aliyuncs.com/api/v1/mcps/QwenImage/sse \
  -k DASHSCOPE_API_KEY \
  call_command modelstudio_qwen_image_gen -a prompt="A cinematic sunset over a cyberpunk city" size=1024*1024
```

图片编辑示例：

```bash
$PYTHON_CMD -m weclaw.agent.mcp_client \
  -u https://dashscope.aliyuncs.com/api/v1/mcps/QwenImage/sse \
  -k DASHSCOPE_API_KEY \
  call_command modelstudio_qwen_image_edit -a image_url=https://example.com/photo.jpg prompt="将背景改为星空"
```

## Notes

- 需要 DashScope API Key（环境变量 `DASHSCOPE_API_KEY`）
- **每次调用必须同时提供 `-u`（base-url）和 `-k`（api-key，环境变量名）参数**
- 使用清晰、详细的 prompt 可获得更好的图片质量
- 图片编辑时，`image_url` 必须为公网可访问的 URL，且不能包含中文字符
- 注意 DashScope 配额限制
- **无需安装任何额外 Python 包，直接使用 `python -m weclaw.agent.mcp_client` 即可**
- 如果以上工具列表不满足需求，可使用 `list-tools` 命令获取所有可用工具：
  ```bash
  $PYTHON_CMD -m weclaw.agent.mcp_client \
    -u https://dashscope.aliyuncs.com/api/v1/mcps/QwenImage/sse \
    -k DASHSCOPE_API_KEY \
    list-tools
  ```
