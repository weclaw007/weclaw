<template>
  <div class="chat-view">
    <!-- 人格设置栏 -->
    <div class="persona-bar">
      <el-icon class="persona-icon" :size="18"><Avatar /></el-icon>
      <el-input
        v-model="personaInput"
        placeholder="设置 AI 人格，如：你是一个友好的助手..."
        size="small"
        clearable
        class="persona-input"
      />
      <el-button
        type="primary"
        size="small"
        :icon="Check"
        @click="handleSetPersona"
        :disabled="!connected || personaInput === currentPersona"
        class="persona-btn"
      >
        设置
      </el-button>
    </div>

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
            <template v-else>
              <!-- 语音消息：带播放按钮 -->
              <div v-if="msg.audioData" class="voice-message" @click="playAudio(msg)">
                <el-icon class="voice-play-icon" :size="20">
                  <VideoPlay v-if="!msg.playing" />
                  <VideoPause v-else />
                </el-icon>
                <div class="voice-wave-bars">
                  <span v-for="i in 12" :key="i" class="voice-bar" :class="{ active: msg.playing }"></span>
                </div>
                <span class="voice-duration">{{ msg.audioDuration || '' }}</span>
              </div>
              <!-- 普通文本消息 -->
              <span v-else>{{ msg.content }}</span>
            </template>
          </div>
        </div>
      </div>


    </div>

    <!-- 语音录制遮罩层 -->
    <Transition name="fade">
      <div v-if="isRecording" class="recording-overlay">
        <div class="recording-indicator">
          <div class="recording-wave">
            <span class="wave-bar"></span>
            <span class="wave-bar"></span>
            <span class="wave-bar"></span>
            <span class="wave-bar"></span>
            <span class="wave-bar"></span>
          </div>
          <p class="recording-text">正在录音，点击麦克风按钮停止并发送</p>
        </div>
      </div>
    </Transition>

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
        <el-button type="success" :icon="Microphone" :disabled="!connected" circle class="voice-btn"
          :class="{ recording: isRecording }" @click="toggleRecording" />
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
import { ref, nextTick, watch, onMounted, onUnmounted } from 'vue'
import { Promotion, Check, Microphone, VideoPlay, VideoPause } from '@element-plus/icons-vue'
import MarkdownIt from 'markdown-it'

const props = defineProps({
  connected: Boolean,
  responseBuffers: Object,
  modelsList: Array,
  currentModel: String,
  persona: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['send-message', 'set-persona'])

// ========== 语音录制相关 ==========
const isRecording = ref(false)
let mediaStream = null
let audioContext = null
let scriptProcessor = null
let pcmChunks = []

/**
 * 切换录音状态（点击语音按钮时触发）
 */
async function toggleRecording() {
  if (isRecording.value) {
    // 正在录音 -> 停止并发送
    stopRecordingAndSend()
    return
  }
  // 未在录音 -> 开始录音
  try {
    // 获取麦克风权限，指定 8kHz 单通道
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        sampleRate: 8000,
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
      }
    })

    audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 8000 })
    const source = audioContext.createMediaStreamSource(mediaStream)

    // 使用 ScriptProcessorNode 采集 PCM 数据
    scriptProcessor = audioContext.createScriptProcessor(4096, 1, 1)
    pcmChunks = []

    scriptProcessor.onaudioprocess = (event) => {
      const inputData = event.inputBuffer.getChannelData(0)
      // 将 Float32 转换为 Int16 PCM
      const pcm16 = new Int16Array(inputData.length)
      for (let i = 0; i < inputData.length; i++) {
        const s = Math.max(-1, Math.min(1, inputData[i]))
        pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
      }
      pcmChunks.push(new Uint8Array(pcm16.buffer))
    }

    source.connect(scriptProcessor)
    scriptProcessor.connect(audioContext.destination)
    isRecording.value = true
  } catch (err) {
    console.error('无法访问麦克风:', err)
    isRecording.value = false
  }
}

/**
 * 停止录音并发送音频数据
 */
function stopRecordingAndSend() {
  if (!isRecording.value) return
  isRecording.value = false

  // 停止采集
  if (scriptProcessor) {
    scriptProcessor.disconnect()
    scriptProcessor = null
  }
  if (audioContext) {
    audioContext.close()
    audioContext = null
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach((t) => t.stop())
    mediaStream = null
  }

  if (pcmChunks.length === 0) return

  // 合并所有 PCM 片段
  const totalLength = pcmChunks.reduce((acc, chunk) => acc + chunk.length, 0)
  const merged = new Uint8Array(totalLength)
  let offset = 0
  for (const chunk of pcmChunks) {
    merged.set(chunk, offset)
    offset += chunk.length
  }
  pcmChunks = []

  // 构建 WAV 文件（8kHz, 16bit, 单通道）
  const wavBuffer = encodeWav(merged, 8000, 1, 16)

  // 转为 Base64
  const base64 = uint8ArrayToBase64(wavBuffer)

  // 计算录音时长（秒）
  const durationSec = Math.round(totalLength / (8000 * 2))  // 8kHz, 16bit = 2 bytes/sample
  const durationText = durationSec >= 60
    ? `${Math.floor(durationSec / 60)}:${String(durationSec % 60).padStart(2, '0')}`
    : `${durationSec}"`

  // 添加用户消息（显示为可播放的语音消息）
  messages.value.push({
    role: 'user',
    content: '🎤 [语音消息]',
    audioData: base64,
    audioMime: 'audio/wav',
    audioDuration: durationText,
    playing: false,
  })
  isTyping.value = true
  messages.value.push({ role: 'assistant', content: '' })
  scrollToBottom()

  // 通过 websocket 发送给服务端（新的列表格式）
  emit('send-message', '', (messageId) => {
    currentMessageId.value = messageId
  }, {
    audio: [{ type: 'base64', data: base64, mime: 'audio/wav' }],
  })
}

/**
 * 将 PCM 数据编码为 WAV 格式
 */
function encodeWav(pcmData, sampleRate, numChannels, bitsPerSample) {
  const byteRate = sampleRate * numChannels * (bitsPerSample / 8)
  const blockAlign = numChannels * (bitsPerSample / 8)
  const dataSize = pcmData.length
  const headerSize = 44
  const buffer = new ArrayBuffer(headerSize + dataSize)
  const view = new DataView(buffer)

  // RIFF 头
  writeString(view, 0, 'RIFF')
  view.setUint32(4, 36 + dataSize, true)
  writeString(view, 8, 'WAVE')

  // fmt 子块
  writeString(view, 12, 'fmt ')
  view.setUint32(16, 16, true)          // SubChunk1Size (PCM)
  view.setUint16(20, 1, true)           // AudioFormat (PCM = 1)
  view.setUint16(22, numChannels, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, byteRate, true)
  view.setUint16(32, blockAlign, true)
  view.setUint16(34, bitsPerSample, true)

  // data 子块
  writeString(view, 36, 'data')
  view.setUint32(40, dataSize, true)

  // 写入 PCM 数据
  const output = new Uint8Array(buffer)
  output.set(pcmData, headerSize)

  return output
}

function writeString(view, offset, string) {
  for (let i = 0; i < string.length; i++) {
    view.setUint8(offset + i, string.charCodeAt(i))
  }
}

/**
 * Uint8Array 转 Base64
 */
function uint8ArrayToBase64(uint8Array) {
  let binary = ''
  const len = uint8Array.length
  for (let i = 0; i < len; i++) {
    binary += String.fromCharCode(uint8Array[i])
  }
  return btoa(binary)
}

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
const personaInput = ref('')
const currentPersona = ref('')  // 记录当前已保存的人格，用于判断是否有修改

/**
 * 监听父组件传入的 persona prop 变化，同步到输入框
 */
watch(
  () => props.persona,
  (val) => {
    personaInput.value = val || ''
    currentPersona.value = val || ''
  },
  { immediate: true }
)

/**
 * 点击设置人格按钮
 */
function handleSetPersona() {
  const text = personaInput.value.trim()
  emit('set-persona', text)
  currentPersona.value = text
}

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

// ========== 语音播放相关 ==========
let currentAudioEl = null     // 当前正在播放的 Audio 元素
let currentPlayingMsg = null  // 当前正在播放的消息对象

/**
 * 播放/暂停语音消息
 */
function playAudio(msg) {
  // 如果点击的是正在播放的消息，暂停
  if (currentPlayingMsg === msg && currentAudioEl) {
    if (msg.playing) {
      currentAudioEl.pause()
      msg.playing = false
      return
    } else {
      currentAudioEl.play()
      msg.playing = true
      return
    }
  }

  // 停止之前正在播放的音频
  stopCurrentAudio()

  // 创建新的 Audio 元素并播放
  const dataUrl = `data:${msg.audioMime};base64,${msg.audioData}`
  currentAudioEl = new Audio(dataUrl)
  currentPlayingMsg = msg
  msg.playing = true

  currentAudioEl.addEventListener('ended', () => {
    msg.playing = false
    currentAudioEl = null
    currentPlayingMsg = null
  })

  currentAudioEl.addEventListener('error', (e) => {
    console.error('音频播放失败:', e)
    msg.playing = false
    currentAudioEl = null
    currentPlayingMsg = null
  })

  currentAudioEl.play().catch((err) => {
    console.error('音频播放失败:', err)
    msg.playing = false
    currentAudioEl = null
    currentPlayingMsg = null
  })
}

/**
 * 停止当前正在播放的音频
 */
function stopCurrentAudio() {
  if (currentAudioEl) {
    currentAudioEl.pause()
    currentAudioEl.currentTime = 0
    currentAudioEl = null
  }
  if (currentPlayingMsg) {
    currentPlayingMsg.playing = false
    currentPlayingMsg = null
  }
}

// 组件卸载时清理音频资源
onUnmounted(() => {
  stopCurrentAudio()
})

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
  position: relative;
}

/* 人格设置栏 */
.persona-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 20px;
  background: #f0f5ff;
  border-bottom: 1px solid #d9e4f5;
}

.persona-icon {
  color: #409eff;
  flex-shrink: 0;
}

.persona-input {
  flex: 1;
}

.persona-input :deep(.el-input__inner) {
  font-size: 13px;
}

.persona-btn {
  flex-shrink: 0;
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
  position: relative;
    z-index: 210;
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
/* 语音消息播放样式 */
.voice-message {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 8px;
  min-width: 120px;
  transition: background 0.2s;
  user-select: none;
}

.voice-message:hover {
  background: rgba(255, 255, 255, 0.15);
}

.voice-play-icon {
  flex-shrink: 0;
  color: #fff;
  transition: transform 0.15s;
}

.voice-message:active .voice-play-icon {
  transform: scale(0.9);
}

.voice-wave-bars {
  display: flex;
  align-items: center;
  gap: 2px;
  height: 20px;
  flex: 1;
}

.voice-bar {
  width: 3px;
  height: 6px;
  background: rgba(255, 255, 255, 0.6);
  border-radius: 2px;
  transition: height 0.15s ease;
}

.voice-bar:nth-child(1) {
  height: 8px;
}

.voice-bar:nth-child(2) {
  height: 12px;
}

.voice-bar:nth-child(3) {
  height: 16px;
}

.voice-bar:nth-child(4) {
  height: 10px;
}

.voice-bar:nth-child(5) {
  height: 18px;
}

.voice-bar:nth-child(6) {
  height: 14px;
}

.voice-bar:nth-child(7) {
  height: 20px;
}

.voice-bar:nth-child(8) {
  height: 12px;
}

.voice-bar:nth-child(9) {
  height: 16px;
}

.voice-bar:nth-child(10) {
  height: 10px;
}

.voice-bar:nth-child(11) {
  height: 14px;
}

.voice-bar:nth-child(12) {
  height: 8px;
}

.voice-bar.active {
  animation: voice-wave-play 0.6s ease-in-out infinite alternate;
}

.voice-bar.active:nth-child(1) {
  animation-delay: 0.00s;
}

.voice-bar.active:nth-child(2) {
  animation-delay: 0.05s;
}

.voice-bar.active:nth-child(3) {
  animation-delay: 0.10s;
}

.voice-bar.active:nth-child(4) {
  animation-delay: 0.15s;
}

.voice-bar.active:nth-child(5) {
  animation-delay: 0.20s;
}

.voice-bar.active:nth-child(6) {
  animation-delay: 0.25s;
}

.voice-bar.active:nth-child(7) {
  animation-delay: 0.30s;
}

.voice-bar.active:nth-child(8) {
  animation-delay: 0.35s;
}

.voice-bar.active:nth-child(9) {
  animation-delay: 0.40s;
}

.voice-bar.active:nth-child(10) {
  animation-delay: 0.45s;
}

.voice-bar.active:nth-child(11) {
  animation-delay: 0.50s;
}

.voice-bar.active:nth-child(12) {
  animation-delay: 0.55s;
}

@keyframes voice-wave-play {
  0% {
    height: 4px;
    background: rgba(255, 255, 255, 0.5);
  }

  100% {
    height: 20px;
    background: rgba(255, 255, 255, 0.95);
  }
}

.voice-duration {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.8);
  flex-shrink: 0;
  min-width: 24px;
  text-align: right;
}
/* 语音按钮 */
.voice-btn {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  transition: all 0.2s ease;
}

.voice-btn.recording {
  background-color: #f56c6c !important;
  border-color: #f56c6c !important;
  animation: pulse-recording 1s infinite;
  position: relative;
  z-index: 220;
}

@keyframes pulse-recording {

  0%,
  100% {
    transform: scale(1);
    box-shadow: 0 0 0 0 rgba(245, 108, 108, 0.4);
  }

  50% {
    transform: scale(1.05);
    box-shadow: 0 0 0 8px rgba(245, 108, 108, 0);
  }
}

/* 录音遮罩层 */
.recording-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
  border-radius: 8px;
}

.recording-indicator {
  background: rgba(0, 0, 0, 0.8);
  border-radius: 16px;
  padding: 30px 50px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}

.recording-wave {
  display: flex;
  align-items: center;
  gap: 4px;
  height: 40px;
}

.wave-bar {
  width: 4px;
  height: 10px;
  background: #67c23a;
  border-radius: 2px;
  animation: wave 1.2s ease-in-out infinite;
}

.wave-bar:nth-child(1) {
  animation-delay: 0s;
}

.wave-bar:nth-child(2) {
  animation-delay: 0.15s;
}

.wave-bar:nth-child(3) {
  animation-delay: 0.3s;
}

.wave-bar:nth-child(4) {
  animation-delay: 0.45s;
}

.wave-bar:nth-child(5) {
  animation-delay: 0.6s;
}

@keyframes wave {

  0%,
  100% {
    height: 10px;
  }

  50% {
    height: 36px;
  }
}

.recording-text {
  color: #ffffff;
  font-size: 14px;
  margin: 0;
  font-weight: 500;
}

/* 遮罩层过渡动画 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.25s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
