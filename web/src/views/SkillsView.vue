<template>
  <div class="skills-view">
    <!-- 顶部操作栏 -->
    <div class="skills-header">
      <div class="header-left">
        <el-button :icon="Refresh" @click="refreshSkills" :loading="loading">
          刷新
        </el-button>
        <el-input
          v-model="searchText"
          placeholder="搜索技能..."
          :prefix-icon="Search"
          clearable
          size="default"
          class="search-input"
        />
        <span class="skills-count" v-if="skills.length > 0">
          共 {{ filteredSkills.length }} 个技能，已启用 {{ enabledCount }} 个
        </span>
        <span class="skills-count" v-else>
          ⏳ 等待加载...
        </span>
      </div>
      <div class="header-right">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="filteredSkills.length"
          layout="prev, pager, next"
          small
          background
        />
      </div>
    </div>

    <!-- 技能卡片列表 -->
    <div class="skills-grid">
      <el-card
        v-for="skill in pagedSkills"
        :key="skill.name"
        class="skill-card"
        :class="{ 'skill-card-with-env': skill.envName }"
        shadow="hover"
      >
        <div class="skill-card-header">
          <div class="skill-info">
            <div class="skill-name">
              <span class="skill-emoji">{{ skill.emoji || '🔧' }}</span>
              <strong :class="{ 'skill-name-warning': skill.envName && !skill.primaryEnv }">
                {{ skill.name }}
                <el-icon v-if="skill.envName && !skill.primaryEnv" class="warning-icon"><WarningFilled /></el-icon>
              </strong>
            </div>
            <p class="skill-desc">{{ skill.description }}</p>
            <div class="skill-tags">
              <el-tag
                :type="skill.builtin ? 'info' : 'primary'"
                size="small"
                effect="plain"
              >
                {{ skill.builtin ? 'openclaw-bundled' : 'third-party' }}
              </el-tag>
            </div>
          </div>
          <div class="skill-actions">
            <el-switch
              :model-value="skill.enabled"
              @change="(val) => toggleSkill(skill, val)"
              :active-text="'启用'"
              :inactive-text="'禁用'"
            />
          </div>
        </div>

        <!-- API Key 配置 -->
        <div v-if="skill.envName" class="skill-env">
          <el-divider />
          <div class="env-row">
            <el-input
              :model-value="getApiKeyInput(skill.name)"
              @update:model-value="(val) => setApiKeyInput(skill.name, val)"
              :placeholder="`请输入 ${skill.envName}`"
              type="password"
              show-password
              size="small"
              class="env-input"
            >
              <template #prepend>{{ skill.envName }}</template>
            </el-input>
            <el-button
              type="danger"
              size="small"
              @click="saveApiKey(skill)"
              :loading="savingStates[skill.name] || false"
            >
              保存
            </el-button>
          </div>
        </div>
      </el-card>
    </div>

    <!-- 空状态 -->
    <!-- 搜索无结果 -->
    <el-empty v-if="filteredSkills.length === 0 && skills.length > 0" description="没有找到匹配的技能" />
    <!-- 空状态 -->
    <el-empty v-if="skills.length === 0 && !loading" description="暂无技能数据" />
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { Refresh, Search, WarningFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  skills: {
    type: Array,
    default: () => [],
  },
  connected: Boolean,
})

const emit = defineEmits(['refresh-skills', 'toggle-skill', 'save-api-key'])

const loading = ref(false)
const currentPage = ref(1)
const searchText = ref('')
const pageSize = 9

// 独立管理每个技能的 API Key 输入值和保存状态
const apiKeyInputs = reactive({})
const savingStates = reactive({})

/**
 * 已启用的技能数量
 */
const enabledCount = computed(() => {
  return props.skills.filter((s) => s.enabled).length
})

/**
 * 搜索过滤后的技能列表
 */
const filteredSkills = computed(() => {
  const keyword = searchText.value.trim().toLowerCase()
  if (!keyword) return props.skills
  return props.skills.filter((s) => {
    return (
      (s.name && s.name.toLowerCase().includes(keyword)) ||
      (s.description && s.description.toLowerCase().includes(keyword))
    )
  })
})

/**
 * 当前页的技能列表
 */
const pagedSkills = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return filteredSkills.value.slice(start, start + pageSize)
})

/**
 * 获取技能的 API Key 输入值
 */
function getApiKeyInput(skillName) {
  return apiKeyInputs[skillName] ?? ''
}

/**
 * 设置技能的 API Key 输入值
 */
function setApiKeyInput(skillName, value) {
  apiKeyInputs[skillName] = value
}

/**
 * 初始化技能的 API Key 输入值（仅在未手动编辑过时设置）
 */
function initApiKeyInputs(skills) {
  for (const skill of skills) {
    if (skill.envName && !(skill.name in apiKeyInputs)) {
      apiKeyInputs[skill.name] = skill.primaryEnv || ''
    }
  }
}

/**
 * 刷新技能列表
 */
async function refreshSkills() {
  loading.value = true
  emit('refresh-skills')
  // 等待一段时间让数据加载
  setTimeout(() => {
    loading.value = false
  }, 1500)
}

/**
 * 启用/禁用技能
 */
function toggleSkill(skill, enabled) {
  emit('toggle-skill', skill.name, enabled)
}

/**
 * 保存 API Key
 */
function saveApiKey(skill) {
  const value = apiKeyInputs[skill.name] || ''
  if (!value) {
    ElMessage.warning('请输入 API Key')
    return
  }
  savingStates[skill.name] = true
  emit('save-api-key', skill.name, skill.envName, value)
  // 模拟保存完成（后续可改为等待 WebSocket 回调）
  setTimeout(() => {
    savingStates[skill.name] = false
    ElMessage.success('API Key 已保存')
  }, 500)
}

// 技能数据或搜索条件变化时重置分页
watch(
  [() => props.skills.length, searchText],
  () => {
    const total = filteredSkills.value.length
    if (currentPage.value > Math.ceil(total / pageSize)) {
      currentPage.value = 1
    }
  }
)

// 当技能列表加载/刷新时，初始化 API Key 输入值
watch(
  () => props.skills,
  (skills) => {
    if (skills && skills.length > 0) {
      initApiKeyInputs(skills)
    }
  },
  { immediate: true }
)
</script>

<style scoped>
.skills-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 20px;
  background: #ffffff;
  border-radius: 8px;
}

/* 顶部操作栏 */
.skills-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 12px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.search-input {
  width: 220px;
}

.skills-count {
  font-size: 14px;
  color: #606266;
}

/* 技能卡片网格 */
.skills-grid {
  flex: 1;
  overflow-y: auto;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  align-content: start;
}

.skill-card {
  transition: all 0.3s;
}

.skill-card :deep(.el-card__body) {
  padding: 24px;
  min-height: 140px;
}

.skill-card-with-env :deep(.el-card__body) {
  min-height: 220px;
}

.skill-card:hover {
  transform: translateY(-2px);
}

.skill-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.skill-info {
  flex: 1;
  min-width: 0;
}

.skill-name {
  font-size: 16px;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.skill-emoji {
  font-size: 20px;
}

.skill-name-warning {
  color: #e6a23c;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.warning-icon {
  font-size: 16px;
  color: #e6a23c;
}

.skill-desc {
  font-size: 13px;
  color: #909399;
  margin: 0 0 8px 0;
  line-height: 1.5;
}

.skill-tags {
  display: flex;
  gap: 6px;
}

.skill-actions {
  flex-shrink: 0;
}

/* API Key 行 */
.skill-env {
  margin-top: 4px;
}

.skill-env :deep(.el-divider) {
  margin: 12px 0;
}

.env-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.env-input {
  flex: 1;
}
</style>
