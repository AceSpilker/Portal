<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Collection as IconApps, Picture as IconLib, Setting as IconGeneral } from '@element-plus/icons-vue'
import { filterElementIcons } from '../utils/elementIcons'
import { useSettingsStore } from '../stores/settings'

const settingsStore = useSettingsStore()

type MenuKey = 'general' | 'apps' | 'icons'
const active = ref<MenuKey>('general')
const saving = ref(false)

// ---- 常规设置 ----
const siteName = ref('')

// ---- 应用配置 ----
const tagOptions = ref<string[]>([])
const newTag = ref('')

// ---- 图标库 ----
const iconSearch = ref('')
const favDraft = ref<string[]>([])
const filteredIcons = computed(() => filterElementIcons(iconSearch.value))

onMounted(async () => {
  await settingsStore.load(true)
  siteName.value = settingsStore.siteName
  tagOptions.value = [...settingsStore.tagOptions]
  favDraft.value = [...settingsStore.iconFavorites]
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

function toggleFav(name: string) {
  favDraft.value = favDraft.value.includes(name)
    ? favDraft.value.filter((x) => x !== name)
    : [...favDraft.value, name]
  if (favDraft.value.length > 100) {
    favDraft.value = favDraft.value.slice(0, 100)
    ElMessage.warning('常用图标最多 100 个')
  }
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

function saveIcons() {
  save({ 'apps.icon_favorites': [...favDraft.value] }, '常用图标已保存')
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
        <el-menu-item index="icons">
          <el-icon><component :is="IconLib" /></el-icon>
          <span>图标库</span>
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

      <template v-else-if="active === 'icons'">
        <header class="panel-head">
          <h3>图标库</h3>
          <p>
            管理图标选择器的「常用」精选（当前 {{ favDraft.length }} 个）——点击下方图标加入/移出常用，
            保存后新建应用、分组弹窗的图标选择器会优先展示常用图标。
          </p>
        </header>
        <div class="panel-body">
          <el-input
            v-model="iconSearch"
            placeholder="搜索图标名，如 monitor / folder"
            clearable
            style="max-width: 320px"
          />
          <div class="icon-manage-grid">
            <button
              v-for="ic in filteredIcons"
              :key="ic.name"
              type="button"
              class="im-cell"
              :class="{ active: favDraft.includes(ic.name) }"
              :title="ic.name"
              @click="toggleFav(ic.name)"
            >
              <component :is="ic.component" class="im-svg" />
              <span class="im-name">{{ ic.name }}</span>
            </button>
            <div v-if="!filteredIcons.length" class="im-empty">没有匹配的图标</div>
          </div>
          <el-button
            type="primary"
            class="btn-gradient"
            :loading="saving"
            style="margin-top: 16px"
            @click="saveIcons"
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
/* 图标库管理 */
.icon-manage-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(86px, 1fr));
  gap: 6px;
  max-height: 460px;
  overflow-y: auto;
  padding: 8px;
  border: 1px solid var(--p-card-border);
  border-radius: 12px;
}
.im-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  padding: 10px 4px 7px;
  border: 1px solid var(--p-card-border);
  border-radius: 10px;
  background: #fff;
  color: var(--p-text);
  cursor: pointer;
  transition:
    border-color 0.12s,
    background 0.12s,
    color 0.12s;
}
.im-cell:hover {
  border-color: var(--p-primary);
  color: var(--p-primary);
}
.im-cell.active {
  background: rgba(91, 95, 241, 0.1);
  border-color: var(--p-primary);
  color: var(--p-primary);
}
.im-svg {
  width: 20px;
  height: 20px;
}
.im-name {
  font-size: 10px;
  max-width: 78px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--p-muted);
}
.im-cell.active .im-name {
  color: var(--p-primary);
}
.im-empty {
  grid-column: 1 / -1;
  text-align: center;
  color: var(--p-muted);
  font-size: 13px;
  padding: 24px 0;
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
