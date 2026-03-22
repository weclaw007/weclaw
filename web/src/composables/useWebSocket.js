import { ref, onMounted, onUnmounted } from 'vue'

/**
 * WebSocket 连接管理 composable
 * 封装与后端 agent 的 WebSocket 通信逻辑
 */
export function useWebSocket(url = 'ws://localhost:4567') {
  const ws = ref(null)
  const connected = ref(false)
  const skillsList = ref([])
  const modelsList = ref([])
  const defaultModel = ref('')
  const currentModel = ref('')
  const persona = ref('')              // 当前 agent 人格设置
  const responseBuffers = ref({})      // { messageId: string }
  const responseFutures = ref({})      // { messageId: { resolve, reject } }
  const serverPushHandlers = ref([])   // 服务端主动推送的消息回调列表

  /**
   * 建立 WebSocket 连接
   */
  function connect() {
    if (ws.value && ws.value.readyState === WebSocket.OPEN) return

    ws.value = new WebSocket(url)

    ws.value.onopen = () => {
      connected.value = true
      console.log('[WebSocket] 已连接:', url)
      // 连接成功后自动获取技能、模型列表和人格配置
      sendSystemMessage('get_skills')
      sendSystemMessage('get_models')
      sendSystemMessage('get_persona')
    }

    ws.value.onmessage = (event) => {
      try {
        const response = JSON.parse(event.data)
        handleMessage(response)
      } catch (e) {
        console.error('[WebSocket] JSON 解析失败:', e)
      }
    }

    ws.value.onclose = () => {
      connected.value = false
      console.log('[WebSocket] 连接已关闭')
      // 清理未完成的 promise
      Object.values(responseFutures.value).forEach(({ reject }) => {
        reject(new Error('WebSocket 连接已关闭'))
      })
      responseFutures.value = {}
    }

    ws.value.onerror = (err) => {
      console.error('[WebSocket] 错误:', err)
    }
  }

  /**
   * 处理收到的消息
   */
  function handleMessage(response) {
    const messageId = response.id || ''
    const msgType = response.type || ''

    console.log('[WebSocket 收到消息]', { id: messageId, type: msgType })

    if (msgType === 'tool') {
      // 服务端通知消息，直接回复服务端
      replyToolMessage(messageId, response)
      return
    }

    if (['start', 'chunk', 'end'].includes(msgType)) {
      handleStreamMessage(messageId, msgType, response)
    } else if (msgType === 'system') {
      handleSystemMessage(response)
    } else if (msgType === 'error') {
      const errorMsg = response.error || '未知错误'
      responseBuffers.value[messageId] = `❌ 错误: ${errorMsg}`
      const future = responseFutures.value[messageId]
      if (future) {
        future.resolve(responseBuffers.value[messageId])
        delete responseFutures.value[messageId]
      }
    }
  }

  /**
   * 回复服务端的 tool 消息
   * 服务端通过 send_and_wait 发送 tool 消息并等待前端回复
   */
  function replyToolMessage(messageId, response) {
    if (!ws.value || ws.value.readyState !== WebSocket.OPEN) {
      console.warn('[WebSocket] 未连接，无法回复 tool 消息')
      return
    }

    const reply = {
      id: messageId,
      type: 'tool',
      status: 'unsupported tool message',
    }

    ws.value.send(JSON.stringify(reply))
    console.log('[WebSocket] 回复 tool 消息:', reply)
  }

  /**
   * 处理流式消息
   */
  function handleStreamMessage(messageId, msgType, response) {
    if (msgType === 'start') {
      responseBuffers.value[messageId] = ''
    } else if (msgType === 'chunk') {
      const chunk = response.chunk || ''
      responseBuffers.value[messageId] = (responseBuffers.value[messageId] || '') + chunk
    } else if (msgType === 'end') {
      const future = responseFutures.value[messageId]
      if (future) {
        // 用户发起的请求，resolve 对应的 promise
        future.resolve(responseBuffers.value[messageId])
        delete responseFutures.value[messageId]
      } else {
        // 服务端主动推送的消息（如定时任务触发），通知所有注册的回调
        const content = responseBuffers.value[messageId] || ''
        serverPushHandlers.value.forEach((handler) => handler(content, messageId))
      }
      delete responseBuffers.value[messageId]
    }
  }

  /**
   * 注册服务端主动推送消息的处理回调
   * @param {Function} handler - (content: string, messageId: string) => void
   * @returns {Function} 取消注册的函数
   */
  function onServerPush(handler) {
    serverPushHandlers.value.push(handler)
    return () => {
      const idx = serverPushHandlers.value.indexOf(handler)
      if (idx !== -1) serverPushHandlers.value.splice(idx, 1)
    }
  }

  /**
   * 处理系统消息
   */
  function handleSystemMessage(response) {
    const action = response.action
    if (action === 'get_skills') {
      const skills = response.skills || []
      skillsList.value = skills
      console.log(`[WebSocket] 获取到 ${skills.length} 个技能`)
    } else if (action === 'get_models') {
      modelsList.value = response.models || []
      defaultModel.value = response.default || ''
      currentModel.value = response.current || defaultModel.value
      console.log(`[WebSocket] 获取到 ${modelsList.value.length} 个模型，当前: ${currentModel.value}`)
    } else if (action === 'enable_skill' || action === 'disable_skill') {
      // 后端确认技能状态变更，同步更新本地数据
      const skillName = response.skill_name
      const enabled = action === 'enable_skill'
      const skill = skillsList.value.find((s) => s.name === skillName)
      if (skill) {
        skill.enabled = enabled
        console.log(`[WebSocket] 技能 ${skillName} 已${enabled ? '启用' : '禁用'}`)
      }
    } else if (action === 'get_persona') {
      persona.value = response.persona || ''
      console.log(`[WebSocket] 获取到人格设置: ${persona.value.slice(0, 50) || '(未设置)'}`)
    } else if (action === 'set_persona') {
      if (response.success) {
        console.log('[WebSocket] 人格设置已保存')
        // 刷新人格配置
        sendSystemMessage('get_persona')
      } else {
        console.error(`[WebSocket] 设置人格失败: ${response.error || '未知错误'}`)
      }
    } else if (action === 'save_api_key') {
      // 后端确认 API Key 保存结果
      const skillName = response.skill_name
      const success = response.success
      if (success) {
        console.log(`[WebSocket] 技能 ${skillName} 的 API Key 已保存到 .env 文件`)
        // 刷新技能列表以更新环境变量显示状态
        sendSystemMessage('get_skills')
      } else {
        console.error(`[WebSocket] 保存 API Key 失败: ${response.error || '未知错误'}`)
      }
    } else if (action === 'save_env_list') {
      // 后端确认批量保存环境变量结果
      const skillName = response.skill_name
      const success = response.success
      if (success) {
        console.log(`[WebSocket] 技能 ${skillName} 的环境变量已批量保存到 .env 文件`)
        // 刷新技能列表以更新环境变量显示状态
        sendSystemMessage('get_skills')
      } else {
        console.error(`[WebSocket] 批量保存环境变量失败: ${response.error || '未知错误'}`)
      }
    }
  }

  /**
   * 生成唯一消息 ID
   */
  function generateId() {
    return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`
  }

  /**
   * 发送用户消息（返回 Promise，流式更新通过 onChunk 回调）
   */
  function sendUserMessage(text) {
    return new Promise((resolve, reject) => {
      if (!ws.value || ws.value.readyState !== WebSocket.OPEN) {
        reject(new Error('WebSocket 未连接'))
        return
      }

      const messageId = generateId()
      const payload = {
        id: messageId,
        type: 'user',
        text,
      }

      responseBuffers.value[messageId] = ''
      responseFutures.value[messageId] = { resolve, reject }

      ws.value.send(JSON.stringify(payload))
      console.log('[WebSocket] 发送消息:', payload)

      // 返回 messageId 以便外部监听 buffer 变化
      resolve.__messageId = messageId
      // 改用返回对象形式
      resolve({
        messageId, promise: new Promise((res, rej) => {
          responseFutures.value[messageId] = { resolve: res, reject: rej }
        })
      })
    })
  }

  /**
   * 发送用户消息 - 简化版，返回 { messageId, promise }
   */
  function sendMessage(text, extra = {}) {
    if (!ws.value || ws.value.readyState !== WebSocket.OPEN) {
      return { messageId: null, promise: Promise.reject(new Error('WebSocket 未连接')) }
    }

    const messageId = generateId()
    const payload = {
      id: messageId,
      type: 'user',
      text,
      ...extra,
    }

    responseBuffers.value[messageId] = ''

    const promise = new Promise((resolve, reject) => {
      responseFutures.value[messageId] = { resolve, reject }
    })

    ws.value.send(JSON.stringify(payload))
    console.log('[WebSocket] 发送消息:', payload)

    return { messageId, promise }
  }

  /**
   * 发送系统消息
   */
  function sendSystemMessage(action, extra = {}) {
    if (!ws.value || ws.value.readyState !== WebSocket.OPEN) {
      console.warn('[WebSocket] 未连接，无法发送系统消息')
      return
    }

    const payload = {
      type: 'system',
      action,
      ...extra,
    }

    ws.value.send(JSON.stringify(payload))
    console.log('[WebSocket] 发送系统消息:', payload)
  }

  /**
   * 关闭连接
   */
  function disconnect() {
    if (ws.value) {
      ws.value.close()
      ws.value = null
    }
  }

  /**
   * 清理消息 buffer
   */
  function clearBuffer(messageId) {
    delete responseBuffers.value[messageId]
  }

  onMounted(() => {
    connect()
  })

  onUnmounted(() => {
    disconnect()
  })

  return {
    ws,
    connected,
    skillsList,
    modelsList,
    defaultModel,
    currentModel,
    persona,
    responseBuffers,
    connect,
    disconnect,
    sendMessage,
    sendSystemMessage,
    clearBuffer,
    onServerPush,
  }
}
