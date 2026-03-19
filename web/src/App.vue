<template>
  <el-container class="app-container">
    <!-- 顶部导航 -->
    <el-header class="app-header">
      <div class="header-left">
        <span class="app-logo">🤖</span>
        <h1 class="app-title">WeClaw 机器人</h1>
      </div>
      <div class="header-center">
        <el-menu
          mode="horizontal"
          :default-active="activeTab"
          @select="onTabSelect"
          class="header-menu"
          :ellipsis="false"
        >
          <el-menu-item index="chat">
            <el-icon><ChatDotRound /></el-icon>
            <span>AI 聊天</span>
          </el-menu-item>
          <el-menu-item index="skills">
            <el-icon><Setting /></el-icon>
            <span>技能配置</span>
          </el-menu-item>
        </el-menu>
      </div>
      <div class="header-right">
        <!-- 模型选择 -->
        <el-select
          v-model="selectedModel"
          placeholder="选择模型"
          @change="onModelChange"
          size="default"
          style="width: 220px"
          :disabled="!connected"
        >
          <el-option
            v-for="model in modelsList"
            :key="model"
            :label="model"
            :value="model"
          />
        </el-select>
      </div>
    </el-header>

    <!-- 主内容区 -->
    <el-main class="app-main">
      <ChatView
        v-show="activeTab === 'chat'"
        ref="chatViewRef"
        :connected="connected"
        :response-buffers="responseBuffers"
        :models-list="modelsList"
        :current-model="currentModel"
        @send-message="onSendMessage"
      />
      <SkillsView
        v-show="activeTab === 'skills'"
        :skills="skillsList"
        :connected="connected"
        @refresh-skills="onRefreshSkills"
        @toggle-skill="onToggleSkill"
        @save-api-key="onSaveApiKey"
      />
    </el-main>
  </el-container>
</template>

<script setup>
import { ref, watch } from 'vue'
import ChatView from './views/ChatView.vue'
import SkillsView from './views/SkillsView.vue'
import { useWebSocket } from './composables/useWebSocket.js'

const activeTab = ref('chat')
const chatViewRef = ref(null)
const selectedModel = ref('')

// 初始化 WebSocket 连接
const {
  connected,
  skillsList,
  modelsList,
  defaultModel,
  currentModel,
  responseBuffers,
  sendMessage,
  sendSystemMessage,
  clearBuffer,
  onServerPush,
} = useWebSocket()

// 注册服务端主动推送消息的处理回调
onServerPush((content) => {
  chatViewRef.value?.onServerPushMessage(content)
})

/**
 * Tab 切换
 */
function onTabSelect(index) {
  activeTab.value = index
}

/**
 * 模型切换
 */
function onModelChange(modelName) {
  if (modelName) {
    sendSystemMessage('switch_model', { model_name: modelName })
  }
}

/**
 * 发送聊天消息
 */
function onSendMessage(text, callback) {
  const { messageId, promise } = sendMessage(text)

  // 通知 ChatView 消息 ID
  if (callback) callback(messageId)

  // 消息完成后通知 ChatView
  promise
    .then(() => {
      chatViewRef.value?.onMessageComplete()
      clearBuffer(messageId)
    })
    .catch((err) => {
      console.error('消息发送失败:', err)
      chatViewRef.value?.onMessageComplete()
    })
}

/**
 * 刷新技能列表
 */
function onRefreshSkills() {
  sendSystemMessage('get_skills')
}

/**
 * 切换技能状态
 */
function onToggleSkill(skillName, enabled) {
  const action = enabled ? 'enable_skill' : 'disable_skill'
  sendSystemMessage(action, { skill_name: skillName })
}

/**
 * 保存 API Key
 */
function onSaveApiKey(skillName, envName, apiKey) {
  sendSystemMessage('save_api_key', {
    skill_name: skillName,
    env_name: envName,
    api_key: apiKey,
  })
}

// 当模型列表加载后，自动选中当前模型
watch(currentModel, (val) => {
  if (val) selectedModel.value = val
})
</script>

<style scoped>
.app-container {
  height: 100vh;
  display: flex;
  flex-direction: column;
}

/* 顶部导航 */
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: #ffffff;
  border-bottom: 1px solid #ebeef5;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
  height: 60px;
  z-index: 100;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.app-logo {
  font-size: 28px;
}

.app-title {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
  margin: 0;
  white-space: nowrap;
}

.header-center {
  flex: 1;
  display: flex;
  justify-content: center;
}

.header-menu {
  border-bottom: none !important;
}

.header-menu :deep(.el-menu-item) {
  font-size: 14px;
  height: 60px;
  line-height: 60px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

/* 主内容 */
.app-main {
  flex: 1;
  overflow: hidden;
  padding: 16px;
  background: #f5f7fa;
}
</style>
