<template>
  <div class="chat-view">
    <!-- 聊天消息列表 -->
    <div class="chat-messages" ref="messagesContainer">
      <div v-if="messages.length === 0" class="empty-state">
        <el-icon :size="64" color="#c0c4cc"><ChatDotRound /></el-icon>
        <p>开始和 WeClaw 机器人对话吧 🤖</p>
      </div>

      <div
        v-for="(msg, index) in messages"
        :key="index"
        class="message-item"
        :class="msg.role"
      >
        <div class="message-avatar">
          <el-avatar v-if="msg.role === 'user'" :size="36" style="background-color: #409eff">
            <el-icon><User /></el-icon>
          </el-avatar>
          <el-avatar v-else :size="36" style="background-color: #67c23a; font-size: 20px;">
            🤖
          </el-avatar>
        </div>
        <div class="message-content">
          <div class="message-bubble" :class="msg.role">
            <template v-if="msg.role === 'assistant'">
              <!-- 助手消息为空且正在打字时，显示打字动画 -->
              <div v-if="!msg.content && isTyping" class="typing-indicator">
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
              </div>
              <div v-else v-html="renderMarkdown(msg.content)"></div>
            </template>
            <span v-else>{{ msg.content }}</span>
          </div>
        </div>
      </div>


    </div>

    <!-- 输入区域 -->
    <div class="chat-input-area">
      <div class="input-wrapper">
        <el-input
          v-model="inputText"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 4 }"
          placeholder="请输入您的问题..."
          @keydown.enter.exact="handleSend"
          :disabled="!connected"
          resize="none"
        />
        <el-button
          type="primary"
          :icon="Promotion"
          @click="handleSend"
          :disabled="!inputText.trim() || !connected"
          :loading="isTyping"
          circle
          class="send-btn"
        />
      </div>
      <div class="input-tips">
        <span v-if="!connected" class="disconnected-tip">
          <el-icon><WarningFilled /></el-icon>
          WebSocket 未连接
        </span>
        <span v-else class="connected-tip">
          <el-icon><SuccessFilled /></el-icon>
          已连接 · 按 Enter 发送，Shift + Enter 换行
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, watch, onMounted } from 'vue'
import { Promotion } from '@element-plus/icons-vue'
import MarkdownIt from 'markdown-it'

const props = defineProps({
  connected: Boolean,
  responseBuffers: Object,
  modelsList: Array,
  currentModel: String,
})

const emit = defineEmits(['send-message'])

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
})

const inputText = ref('')
const messages = ref([])
const isTyping = ref(false)
const currentMessageId = ref(null)
const messagesContainer = ref(null)

/**
 * 渲染 Markdown 内容
 */
function renderMarkdown(text) {
  if (!text) return ''
  return md.render(text)
}

/**
 * 滚动到底部
 */
function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

/**
 * 发送消息
 */
function handleSend(e) {
  // Shift+Enter 换行
  if (e && e.shiftKey) return

  if (e) e.preventDefault()

  const text = inputText.value.trim()
  if (!text || !props.connected) return

  // 添加用户消息
  messages.value.push({ role: 'user', content: text })
  inputText.value = ''
  isTyping.value = true

  // 添加空的助手消息占位
  messages.value.push({ role: 'assistant', content: '' })
  scrollToBottom()

  // 通知父组件发送消息
  emit('send-message', text, (messageId) => {
    currentMessageId.value = messageId
  })
}

/**
 * 监听 responseBuffers 变化，实时更新流式响应
 */
watch(
  () => props.responseBuffers,
  (buffers) => {
    if (currentMessageId.value && buffers[currentMessageId.value] !== undefined) {
      const content = buffers[currentMessageId.value]
      // 更新最后一条助手消息
      const lastMsg = messages.value[messages.value.length - 1]
      if (lastMsg && lastMsg.role === 'assistant') {
        lastMsg.content = content
        scrollToBottom()
      }
    }
  },
  { deep: true }
)

/**
 * 标记消息接收完成
 */
function onMessageComplete() {
  isTyping.value = false
  currentMessageId.value = null
}

/**
 * 接收服务端主动推送的消息（如定时任务触发）
 */
function onServerPushMessage(content) {
  messages.value.push({ role: 'assistant', content })
  scrollToBottom()
}

// 暴露方法供父组件调用
defineExpose({ onMessageComplete, onServerPushMessage })
</script>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #ffffff;
  border-radius: 8px;
}

/* 消息列表 */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  scroll-behavior: smooth;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #909399;
  gap: 16px;
}

.empty-state p {
  font-size: 16px;
}

/* 消息项 */
.message-item {
  display: flex;
  margin-bottom: 20px;
  gap: 12px;
}

.message-item.user {
  flex-direction: row-reverse;
}

.message-avatar {
  flex-shrink: 0;
}

.message-content {
  max-width: 70%;
}

.message-bubble {
  padding: 12px 16px;
  border-radius: 12px;
  line-height: 1.6;
  word-break: break-word;
}

.message-bubble.user {
  background: #409eff;
  color: #fff;
  border-top-right-radius: 4px;
}

.message-bubble.assistant {
  background: #f4f4f5;
  color: #303133;
  border-top-left-radius: 4px;
}

/* Markdown 内容样式 */
.message-bubble.assistant :deep(p) {
  margin: 0 0 8px 0;
}

.message-bubble.assistant :deep(p:last-child) {
  margin-bottom: 0;
}

.message-bubble.assistant :deep(code) {
  background: #e6e8eb;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
}

.message-bubble.assistant :deep(pre) {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 8px 0;
}

.message-bubble.assistant :deep(pre code) {
  background: none;
  padding: 0;
  color: inherit;
}

/* 打字指示器 */
.typing-indicator {
  display: flex;
  gap: 4px;
  align-items: center;
  padding: 4px 0;
}

.typing-dot {
  width: 8px;
  height: 8px;
  background: #909399;
  border-radius: 50%;
  animation: typing 1.4s infinite ease-in-out;
}

.typing-dot:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-dot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes typing {
  0%, 80%, 100% {
    transform: scale(0.6);
    opacity: 0.4;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}

/* 输入区域 */
.chat-input-area {
  padding: 16px 20px;
  border-top: 1px solid #ebeef5;
  background: #fafafa;
  border-radius: 0 0 8px 8px;
}

.input-wrapper {
  display: flex;
  gap: 12px;
  align-items: flex-end;
}

.input-wrapper :deep(.el-textarea__inner) {
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 14px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}

.send-btn {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
}

.input-tips {
  margin-top: 8px;
  font-size: 14px;
  color: #909399;
}

.disconnected-tip {
  color: #f56c6c;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
}

.disconnected-tip .el-icon {
  font-size: 16px;
}

.connected-tip {
  color: #67c23a;
  font-size: 14px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 6px;
}

.connected-tip .el-icon {
  font-size: 16px;
}
</style>
