<template>
  <div class="skills-view">
    <!-- 顶部操作栏 -->
    <div class="skills-header">
      <div class="header-left">
        <el-button :icon="Refresh" @click="refreshSkills" :loading="loading">
          刷新
        </el-button>
        <el-input v-model="searchText" placeholder="搜索技能..." :prefix-icon="Search" clearable size="default"
          class="search-input" />
        <span class="skills-count" v-if="skills.length > 0">
          共 {{ filteredSkills.length }} 个技能，已启用 {{ enabledCount }} 个
        </span>
        <span class="skills-count" v-else>
          ⏳ 等待加载...
        </span>
      </div>
      <div class="header-right">
        <el-pagination v-model:current-page="currentPage" :page-size="pageSize" :total="filteredSkills.length"
          layout="prev, pager, next" small background />
      </div>
    </div>

    <!-- 技能卡片列表 -->
    <div class="skills-grid">
      <el-card v-for="skill in pagedSkills" :key="skill.name" class="skill-card"
        :class="{ 'skill-card-with-env': skill.envList && skill.envList.length > 0 }" shadow="hover">
        <div class="skill-card-header">
          <div class="skill-info">
            <div class="skill-name">
              <span class="skill-emoji">{{ skill.emoji || '🔧' }}</span>
              <strong :class="{ 'skill-name-warning': hasUnsetEnv(skill) }">
                {{ skill.name }}
                <el-icon v-if="hasUnsetEnv(skill)" class="warning-icon">
                  <WarningFilled />
                </el-icon>
              </strong>
            </div>
            <p class="skill-desc">{{ skill.description }}</p>
            <div class="skill-tags">
              <el-tag :type="skill.builtin ? 'info' : 'primary'" size="small" effect="plain">
                {{ skill.builtin ? 'weclaw-bundled' : 'third-party' }}
              </el-tag>
            </div>
          </div>
          <div class="skill-actions">
            <el-switch :model-value="skill.enabled" @change="(val) => toggleSkill(skill, val)" :active-text="'启用'"
              :inactive-text="'禁用'" />
          </div>
        </div>

        <!-- 环境变量配置 -->
        <div v-if="skill.envList && skill.envList.length > 0" class="skill-env">
          <el-divider />
          <div v-for="(envItem, idx) in skill.envList" :key="envItem.envName" class="env-row"
            :class="{ 'env-row-gap': idx > 0 }">
            <el-input :model-value="getEnvInput(skill.name, envItem.envName)"
              @update:model-value="(val) => setEnvInput(skill.name, envItem.envName, val)"
              :placeholder="`请输入 ${envItem.envName}`" type="password" show-password size="small" class="env-input">
              <template #prepend>{{ envItem.envName }}</template>
            </el-input>
          </div>
          <div class="env-save-row">
            <el-button type="danger" size="small" @click="saveEnvList(skill)"
              :loading="savingStates[skill.name] || false">
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

const emit = defineEmits(['refresh-skills', 'toggle-skill', 'save-api-key', 'save-env-list'])

const loading = ref(false)
const currentPage = ref(1)
const searchText = ref('')
const pageSize = 9

// 独立管理每个技能的环境变量输入值和保存状态
// envInputs 结构: { skillName: { envName: value, ... }, ... }
const envInputs = reactive({})
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
 * 判断技能是否有未设置的环境变量
 */
function hasUnsetEnv(skill) {
  if (!skill.envList || skill.envList.length === 0) return false
  return skill.envList.some((item) => !item.envValue)
}

/**
 * 获取技能某个环境变量的输入值
 */
function getEnvInput(skillName, envName) {
  return envInputs[skillName]?.[envName] ?? ''
}

/**
 * 设置技能某个环境变量的输入值
 */
function setEnvInput(skillName, envName, value) {
  if (!envInputs[skillName]) {
    envInputs[skillName] = {}
  }
  envInputs[skillName][envName] = value
}

/**
 * 初始化技能的环境变量输入值（仅在未手动编辑过时设置）
 */
function initEnvInputs(skills) {
  for (const skill of skills) {
    if (skill.envList && skill.envList.length > 0 && !(skill.name in envInputs)) {
      envInputs[skill.name] = {}
      for (const item of skill.envList) {
        envInputs[skill.name][item.envName] = item.envValue || ''
      }
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
 * 批量保存环境变量
 */
function saveEnvList(skill) {
  const inputs = envInputs[skill.name] || {}
  const envList = Object.entries(inputs)
    .filter(([, value]) => value)
    .map(([envName, envValue]) => ({ envName, envValue }))

  if (envList.length === 0) {
    ElMessage.warning('请至少填写一个环境变量')
    return
  }
  savingStates[skill.name] = true
  emit('save-env-list', skill.name, envList)
  // 模拟保存完成（后续可改为等待 WebSocket 回调）
  setTimeout(() => {
    savingStates[skill.name] = false
    ElMessage.success('环境变量已保存')
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

// 当技能列表加载/刷新时，初始化环境变量输入值
watch(
  () => props.skills,
  (skills) => {
    if (skills && skills.length > 0) {
      initEnvInputs(skills)
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
  min-height: 240px;
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

.env-row-gap {
  margin-top: 8px;
}

.env-save-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 10px;
}
.env-input {
  flex: 1;
}
</style>
