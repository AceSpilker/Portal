<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Collection as IconApps, Setting as IconGeneral } from '@element-plus/icons-vue'
import { useSettingsStore } from '../stores/settings'

const settingsStore = useSettingsStore()

type MenuKey = 'general' | 'apps'
const active = ref<MenuKey>('general')
const saving = ref(false)

// ---- 常规设置 ----
const siteName = ref('')

// ---- 应用配置 ----
const tagOptions = ref<string[]>([])
const newTag = ref('')

onMounted(async () => {
  await settingsStore.load(true)
  siteName.value = settingsStore.siteName
  tagOptions.value = [...settingsStore.tagOptions]
})

function addTag() {
  const t = newTag.value.trim()
  if (!t) return
  if (tagOptions.value.includes(t)) {
    ElMessage.warning('该标签已存在')
    return
  }
  if (tagOptions.value.length >= 50) {
    ElMessage.warning('标签选项最多 50 个')
    return
  }
  tagOptions.value = [...tagOptions.value, t]
  newTag.value = ''
}

function removeTag(t: string) {
  tagOptions.value = tagOptions.value.filter((x) => x !== t)
}

async function save(values: Record<string, unknown>, tip: string) {
  saving.value = true
  try {
    await settingsStore.save(values)
    ElMessage.success(tip)
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    saving.value = false
  }
}

function saveGeneral() {
  if (!siteName.value.trim()) {
    ElMessage.warning('站点名称不能为空')
    return
  }
  save({ 'general.site_name': siteName.value.trim() }, '常规设置已保存')
}

function saveTags() {
  save({ 'apps.tag_options': [...tagOptions.value] }, '标签选项已保存')
}
</script>

<template>
  <div class="settings-page">
    <!-- 二级菜单 -->
    <aside class="menu glass">
      <div class="menu-title">系统配置</div>
      <el-menu :default-active="active" class="menu-list" @select="(k: string) => (active = k as MenuKey)">
        <el-menu-item index="general">
          <el-icon><component :is="IconGeneral" /></el-icon>
          <span>常规设置</span>
        </el-menu-item>
        <el-menu-item index="apps">
          <el-icon><component :is="IconApps" /></el-icon>
          <span>应用配置</span>
        </el-menu-item>
      </el-menu>
      <p class="menu-hint">更多配置项（外观、通知、安全、同步等）将随后续阶段开放。</p>
    </aside>

    <!-- 配置面板 -->
    <section class="panel glass">
      <template v-if="active === 'general'">
        <header class="panel-head">
          <h3>常规设置</h3>
          <p>站点基础信息，保存后立即生效。</p>
        </header>
        <el-form label-position="top" class="panel-body" size="large">
          <el-form-item label="站点名称" style="max-width: 360px">
            <el-input v-model="siteName" maxlength="64" placeholder="Portal" />
          </el-form-item>
          <el-button type="primary" class="btn-gradient" :loading="saving" @click="saveGeneral">
            保存
          </el-button>
        </el-form>
      </template>

      <template v-else-if="active === 'apps'">
        <header class="panel-head">
          <h3>应用配置</h3>
          <p>新增 / 编辑应用时的标签候选在此维护，应用表单中只能从候选中选择。</p>
        </header>
        <div class="panel-body">
          <div class="tag-editor">
            <el-tag
              v-for="t in tagOptions"
              :key="t"
              closable
              size="large"
              class="tag-item"
              @close="removeTag(t)"
            >
              {{ t }}
            </el-tag>
            <el-input
              v-model="newTag"
              placeholder="输入新标签后回车"
              class="tag-input"
              maxlength="32"
              @keyup.enter="addTag"
            >
              <template #append>
                <el-button @click="addTag">添加</el-button>
              </template>
            </el-input>
          </div>
          <el-button
            type="primary"
            class="btn-gradient"
            :loading="saving"
            style="margin-top: 16px"
            @click="saveTags"
          >
            保存
          </el-button>
        </div>
      </template>
    </section>
  </div>
</template>

<style scoped>
.settings-page {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: clamp(10px, 1.4vw, 14px);
  align-items: stretch;
}
.menu {
  width: clamp(180px, 16vw, 220px);
  flex-shrink: 0;
  padding: 16px 10px;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}
.menu-title {
  font-weight: 700;
  font-size: 15px;
  padding: 0 12px 12px;
}
.menu-list {
  border-right: none;
  background: transparent;
}
.menu-hint {
  margin-top: auto;
  font-size: 12px;
  color: var(--p-muted);
  padding: 12px 12px 0;
  border-top: 1px dashed var(--p-card-border);
}
.panel {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: clamp(16px, 2vw, 24px);
}
.panel-head {
  margin-bottom: 16px;
}
.panel-head h3 {
  margin: 0 0 6px;
  font-size: 17px;
}
.panel-head p {
  margin: 0;
  color: var(--p-muted);
  font-size: 13px;
}
.tag-editor {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  max-width: 640px;
}
.tag-item {
  font-size: 13px;
}
.tag-input {
  width: 200px;
}

@media (max-width: 767px) {
  .settings-page {
    flex-direction: column;
  }
  .menu {
    width: 100%;
    flex-direction: row;
    align-items: center;
    overflow-x: auto;
  }
  .menu-title,
  .menu-hint {
    display: none;
  }
  .menu-list {
    display: flex;
    flex: 1;
  }
}
</style>
