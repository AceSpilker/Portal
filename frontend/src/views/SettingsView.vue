<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Collection as IconApps,
  Delete as IconDelete,
  Edit as IconEdit,
  Picture as IconLib,
  Setting as IconGeneral,
} from '@element-plus/icons-vue'
import { filterElementIcons } from '../utils/elementIcons'
import { useSettingsStore } from '../stores/settings'
import { useIconLibraryStore } from '../stores/iconLibrary'
import type { CustomIcon } from '../api/icons'
import { isMobile } from '../composables/useIsMobile'

const settingsStore = useSettingsStore()
const iconLibrary = useIconLibraryStore()

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

interface IconCell {
  kind: 'element' | 'custom'
  key: string // element = 图标名；custom = /icons/ 路径
  name: string
  path?: string
  component?: unknown
  icon?: CustomIcon
}

/** 统一图标库网格：自定义图标置顶（可编辑/删除），其后为内置图标（可切换常用精选） */
const iconCells = computed<IconCell[]>(() => {
  const kw = iconSearch.value.trim().toLowerCase()
  const customs = iconLibrary.customIcons
    .filter((c) => !kw || c.name.toLowerCase().includes(kw))
    .map((c) => ({ kind: 'custom' as const, key: c.path, name: c.name, path: c.path, icon: c }))
  const elements = filteredIcons.value.map((ic) => ({
    kind: 'element' as const,
    key: ic.name,
    name: ic.name,
    component: ic.component,
  }))
  return [...customs, ...elements]
})

const isFav = (key: string) => favDraft.value.includes(key)

// 自定义图标编辑弹窗
const iconDialog = ref(false)
const iconSaving = ref(false)
const iconForm = ref({ id: undefined as number | undefined, name: '', data: '', filename: '', preview: '' })
const iconFileInput = ref<HTMLInputElement>()

onMounted(async () => {
  await Promise.all([settingsStore.load(true), iconLibrary.load(true)])
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

function toggleFav(key: string) {
  favDraft.value = favDraft.value.includes(key)
    ? favDraft.value.filter((x) => x !== key)
    : [...favDraft.value, key]
  if (favDraft.value.length > 100) {
    favDraft.value = favDraft.value.slice(0, 100)
    ElMessage.warning('常用图标最多 100 个')
  }
}

// ---- 自定义图标 CRUD ----
function openIconCreate() {
  iconForm.value = { id: undefined, name: '', data: '', filename: '', preview: '' }
  iconDialog.value = true
}

function openIconEdit(icon: CustomIcon) {
  iconForm.value = { id: icon.id, name: icon.name, data: '', filename: '', preview: icon.path }
  iconDialog.value = true
}

async function removeIcon(icon: CustomIcon) {
  try {
    await ElMessageBox.confirm(
      `确定删除自定义图标「${icon.name}」？正在使用的图标无法删除。`,
      '删除图标',
      { type: 'warning', confirmButtonText: '删除' },
    )
  } catch {
    return
  }
  try {
    await iconLibrary.remove(icon.id)
    ElMessage.success('图标已删除')
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

function onIconFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (file.size > 2 * 1024 * 1024) {
    ElMessage.warning('图标文件不能超过 2MB')
    return
  }
  const reader = new FileReader()
  reader.onload = () => {
    const dataUrl = reader.result as string
    iconForm.value.preview = dataUrl
    iconForm.value.data = dataUrl.split(',')[1] ?? ''
    if (!iconForm.value.name) iconForm.value.name = file.name.replace(/\.[^.]+$/, '').slice(0, 32)
  }
  reader.readAsDataURL(file)
}

async function saveIcon() {
  if (!iconForm.value.name.trim()) {
    ElMessage.warning('请填写图标名称')
    return
  }
  if (!iconForm.value.id && !iconForm.value.data) {
    ElMessage.warning('请选择图标图片')
    return
  }
  iconSaving.value = true
  try {
    if (iconForm.value.id) {
      await iconLibrary.update(iconForm.value.id, {
        name: iconForm.value.name.trim(),
        ...(iconForm.value.data ? { data: iconForm.value.data, filename: iconForm.value.filename } : {}),
      })
      ElMessage.success('图标已更新')
    } else {
      await iconLibrary.create({
        name: iconForm.value.name.trim(),
        data: iconForm.value.data,
        filename: iconForm.value.filename,
      })
      ElMessage.success('图标已添加')
    }
    iconDialog.value = false
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    iconSaving.value = false
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
            点击图标加入/移出「常用精选」，选择器会优先展示常用图标；自定义图标置顶展示，
            悬停可编辑或删除（正在被使用的图标无法删除）。上传的图片会自动裁方压缩。
          </p>
        </header>
        <div class="panel-body icons-body">
          <div class="icons-toolbar">
            <el-input
              v-model="iconSearch"
              placeholder="搜索图标名，如 monitor / folder"
              clearable
              class="icons-search"
            />
            <div class="spacer" />
            <el-button type="primary" class="btn-gradient" @click="openIconCreate">
              + 新增图标
            </el-button>
          </div>
          <div class="icon-manage-grid">
            <div
              v-for="cell in iconCells"
              :key="cell.kind + cell.key"
              class="im-cell"
              :class="{ active: isFav(cell.key), custom: cell.kind === 'custom' }"
            >
              <button
                type="button"
                class="im-main"
                :title="cell.kind === 'custom' ? `${cell.name}（点击加入/移出常用精选）` : `${cell.name}（点击加入/移出常用精选）`"
                @click="toggleFav(cell.key)"
              >
                <img v-if="cell.kind === 'custom'" :src="cell.path" :alt="cell.name" class="im-img" />
                <component v-else :is="cell.component" class="im-svg" />
                <span class="im-name">{{ cell.name }}</span>
              </button>
              <div v-if="cell.kind === 'custom'" class="im-ops">
                <button
                  type="button"
                  class="im-op"
                  title="编辑"
                  @click.stop="openIconEdit(cell.icon!)"
                >
                  <el-icon :size="11"><IconEdit /></el-icon>
                </button>
                <button
                  type="button"
                  class="im-op danger"
                  title="删除"
                  @click.stop="removeIcon(cell.icon!)"
                >
                  <el-icon :size="11"><IconDelete /></el-icon>
                </button>
              </div>
            </div>
            <div v-if="!iconCells.length" class="im-empty">没有匹配的图标</div>
          </div>
          <el-button
            type="primary"
            class="btn-gradient"
            :loading="saving"
            style="align-self: flex-start"
            @click="saveIcons"
          >
            保存常用精选（{{ favDraft.length }}）
          </el-button>
        </div>

        <!-- 新增/编辑自定义图标 -->
        <el-dialog
          v-model="iconDialog"
          :title="iconForm.id ? '编辑自定义图标' : '新增自定义图标'"
          :width="isMobile ? '94%' : '420px'"
          append-to-body
        >
          <div class="icon-dialog-body">
            <div class="icon-dialog-preview">
              <img v-if="iconForm.preview" :src="iconForm.preview" alt="" />
              <span v-else>?</span>
            </div>
            <div class="icon-dialog-fields">
              <el-input v-model="iconForm.name" placeholder="图标名称（如 qBittorrent）" maxlength="32" />
              <el-button @click="iconFileInput?.click()">
                {{ iconForm.id && !iconForm.data ? '更换图片' : '选择图片' }}
              </el-button>
              <input
                ref="iconFileInput"
                type="file"
                accept="image/*"
                hidden
                @change="onIconFile"
              />
              <p class="muted-tip">支持 PNG / JPG / SVG / WebP，≤2MB，自动裁方压缩。</p>
            </div>
          </div>
          <template #footer>
            <el-button @click="iconDialog = false">取消</el-button>
            <el-button type="primary" class="btn-gradient" :loading="iconSaving" @click="saveIcon">
              保存
            </el-button>
          </template>
        </el-dialog>
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
.icons-body {
  display: flex;
  flex-direction: column;
  gap: 16px; /* 检索框与图标区等区块间距 */
}
.icons-body :deep(.el-tabs__content) {
  overflow: visible;
}
.icons-search {
  max-width: 320px;
}
.muted-tip {
  margin: 0;
  font-size: 12.5px;
  color: var(--p-muted);
}
.icon-dialog-body {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}
.icon-dialog-preview {
  width: 72px;
  height: 72px;
  flex-shrink: 0;
  border: 1px dashed var(--p-card-border);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  color: var(--p-muted);
  overflow: hidden;
}
.icon-dialog-preview img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.icon-dialog-fields {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
/* 图标库管理 */
.icons-body {
  display: flex;
  flex-direction: column;
  gap: 16px; /* 检索框与图标区等区块间距 */
}
.icons-search {
  max-width: 320px;
}
.icons-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}
.spacer {
  flex: 1;
}
.icon-manage-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: 10px;
  max-height: 460px;
  overflow-y: auto;
  padding: 10px;
  border: 1px solid var(--p-card-border);
  border-radius: 12px;
  align-content: start;
}
.im-cell {
  position: relative;
  border: 1px solid var(--p-card-border);
  border-radius: 10px;
  background: #fff;
  transition: border-color 0.12s, background 0.12s;
}
.im-cell:hover {
  border-color: var(--p-primary);
}
.im-cell.active {
  background: rgba(91, 95, 241, 0.08);
  border-color: var(--p-primary);
}
.im-main {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 12px 6px 9px;
  background: transparent;
  border: none;
  border-radius: 10px;
  color: var(--p-text);
  cursor: pointer;
}
.im-main:hover {
  color: var(--p-primary);
}
.im-cell.active .im-main {
  color: var(--p-primary);
}
.im-svg {
  width: 22px;
  height: 22px;
}
.im-img {
  width: 26px;
  height: 26px;
  object-fit: contain;
  border-radius: 6px;
}
.im-name {
  font-size: 11px;
  max-width: 88px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--p-muted);
}
.im-cell.active .im-name,
.im-main:hover .im-name {
  color: var(--p-primary);
}
/* 悬停显示的自定义图标操作按钮 */
.im-ops {
  position: absolute;
  top: 4px;
  right: 4px;
  display: flex;
  gap: 3px;
  opacity: 0;
  transition: opacity 0.12s;
}
.im-cell:hover .im-ops,
.im-cell.custom:focus-within .im-ops {
  opacity: 1;
}
.im-op {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 50%;
  background: rgba(23, 33, 58, 0.08);
  color: var(--p-text);
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.im-op:hover {
  background: rgba(91, 95, 241, 0.18);
  color: var(--p-primary);
}
.im-op.danger:hover {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
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
