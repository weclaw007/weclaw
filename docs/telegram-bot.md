# Telegram Bot 使用指南

本文档详细介绍如何创建 Telegram 机器人并与 Weclaw 集成，实现随时随地通过 Telegram 与 AI 助手对话。

## 前置条件

- 已安装并配置好 Weclaw（参考 [README](../README.md) 快速上手部分）
- 已安装 Telegram App（[iOS](https://apps.apple.com/app/telegram-messenger/id686449807) / [Android](https://play.google.com/store/apps/details?id=org.telegram.messenger) / [桌面版](https://desktop.telegram.org/)）
- 需要能正常访问 Telegram 网络

## 第一步：创建 Telegram 机器人

### 1. 找到 BotFather

打开 Telegram App，在搜索栏中搜索 **BotFather**（注意是官方认证的，带蓝色勾标识）。

![BotFather](https://core.telegram.org/file/811140763/1/PihKNbjT8UE/03b57814e13713da37)

点击进入与 BotFather 的对话。

### 2. 创建新机器人

向 BotFather 发送以下命令：

```
/newbot
```

### 3. 设置机器人名称

BotFather 会回复要求你输入机器人的**显示名称**（Display Name），例如：

```
Alright, a new bot. How are we going to call it? Please choose a name for your bot.
```

输入你想要的名称，比如：

```
我的AI助手
```

### 4. 设置机器人用户名

接着 BotFather 会要求你设置机器人的**用户名**（Username），用户名必须以 `bot` 结尾：

```
Good. Now let's choose a username for your bot. It must end in `bot`. Like this, for example: TetrisBot or tetris_bot.
```

输入一个唯一的用户名，比如：

```
my_weclaw_ai_bot
```

### 5. 获取 Bot Token

创建成功后，BotFather 会回复 **Done!** 并提供你的 Bot Token，格式类似：

```
Done! Congratulations on your new bot. You will find it at t.me/my_weclaw_ai_bot.
You can now add a description, about section and profile picture for your bot, see /help for a list of commands.

Use this token to access the HTTP API:
7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

Keep your token secure and store it safely, it can be used by anyone to control your bot.
```

> ⚠️ **请妥善保管你的 Token！** 任何拥有此 Token 的人都可以控制你的机器人。

## 第二步：配置 Token

### 1. 写入 .env 文件

打开项目根目录下的 `.env` 文件，添加以下配置：

```bash
# Telegram Bot Token
TELEGRAM_BOT_TOKEN=7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

将 `7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` 替换为你在上一步获取的真实 Token。

### 2. 验证配置

确保 `.env` 文件中的 Token 格式正确，Token 通常由数字、冒号和字母数字混合组成，例如：

```
TELEGRAM_BOT_TOKEN=7123456789:AAHfG3xxxxxxxxxxxxxxxxxxxxxxxxxxx
```

## 第三步：启动 Telegram Bot

### 1. 启动 Weclaw 服务

确保 Weclaw 的 Agent 和 Server 都已启动（参考 README 快速上手部分）：

```bash
# 终端 1：启动 Agent
python -m weclaw.agent.main

# 终端 2：启动 Server（Web UI）
python -m weclaw.server.server
```

### 2. 通过网页 Chat 界面启动

打开浏览器访问 Weclaw Web UI（默认 http://localhost:7860），在聊天输入框中输入：

```
启动 telegram bot
```

Agent 会自动调用 Telegram 技能，启动机器人服务。启动成功后你会看到类似的日志输出：

```
Telegram 机器人启动中...
WebSocket 连接成功
Telegram 机器人运行中...
```

### 3. 开始对话

回到 Telegram App：

1. 搜索你刚创建的机器人用户名（如 `my_weclaw_ai_bot`）
2. 点击 **Start** 或发送 `/start` 开始对话
3. 直接发送任意文本消息，机器人就会通过 Weclaw AI 助手回复你

## 机器人命令

| 命令 | 说明 |
|------|------|
| `/start` | 启动机器人，显示欢迎信息 |
| `/help` | 查看帮助信息 |
| `/stop` | 停止机器人 |

除了命令外，直接发送文本消息或位置信息，机器人都会转发给 AI 助手处理并返回回复。

## 功能特性

- **文本对话**：发送文本消息，AI 助手会智能回复
- **位置信息**：发送位置，AI 助手可以基于地理位置提供服务
- **Markdown 渲染**：AI 的回复会自动转换为 Telegram 支持的富文本格式（加粗、代码块、链接等）
- **实时响应**：通过 WebSocket 流式接收 AI 回复，响应更快

## 常见问题

### Q: 机器人没有回复消息？

1. 检查 Weclaw Agent 是否正常运行（WebSocket 服务是否在 `ws://localhost:4567` 监听）
2. 检查 `.env` 文件中的 `TELEGRAM_BOT_TOKEN` 是否正确
3. 查看终端日志，确认是否有错误信息

### Q: 提示 "请设置环境变量 TELEGRAM_BOT_TOKEN"？

说明 `.env` 文件中没有正确配置 Token，请检查：
- `.env` 文件是否在项目根目录
- Token 格式是否正确（`TELEGRAM_BOT_TOKEN=xxx`，等号两边不要有空格）

### Q: 提示 "服务暂时不可用"？

说明 Telegram Bot 无法连接到 Weclaw 的 WebSocket 服务，请确保：
- Agent 已启动（`python -m weclaw.agent.main`）
- WebSocket 端口 4567 没有被占用或防火墙拦截

### Q: 如何停止机器人？

你可以：
- 在 Telegram 中向机器人发送 `/stop` 命令
- 或在运行 Weclaw 的终端按 `Ctrl+C` 停止服务

## 消息类型支持

以下是 Telegram 支持的消息类型及当前支持状态：

| 消息类型 | 说明 | 状态 |
|---------|------|------|
| 文本消息 | 普通文本聊天消息 | ✅ 已支持 |
| 位置消息 | 发送地理位置坐标 | ✅ 已支持 |
| 图片消息 | 发送照片/图片 | ⬜ 待支持 |
| 语音消息 | 发送语音录音 | ⬜ 待支持 |
| 视频消息 | 发送视频文件 | ⬜ 待支持 |
| 视频备注 | 圆形短视频消息 | ⬜ 待支持 |
| 文件/文档 | 发送各类文件 | ⬜ 待支持 |
| 音频消息 | 发送音乐/音频文件 | ⬜ 待支持 |
| 贴纸消息 | 发送 Telegram 贴纸 | ⬜ 待支持 |
| 动图消息 | 发送 GIF 动画 | ⬜ 待支持 |
| 联系人消息 | 分享联系人信息 | ⬜ 待支持 |
| 实时位置 | 共享实时位置信息 | ⬜ 待支持 |
| 场所/地点 | 发送附近地点信息 | ⬜ 待支持 |
| 投票消息 | 创建投票 | ⬜ 待支持 |
| 掷骰子 | 发送随机动画表情 | ⬜ 待支持 |
| 回复消息 | 引用回复某条消息 | ⬜ 待支持 |
| 转发消息 | 转发其他对话的消息 | ⬜ 待支持 |
| 内联查询 | 在输入框中触发 Bot 查询 | ⬜ 待支持 |
| 回调查询 | 点击内联键盘按钮 | ⬜ 待支持 |

> 💡 随着项目迭代，更多消息类型将逐步支持。如有需求，欢迎提交 Issue 或 PR。
