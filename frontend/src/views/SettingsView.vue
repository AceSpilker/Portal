<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useI18n } from 'vue-i18n'
import {
  Collection as IconApps,
  Connection as IconAccess,
  Delete as IconDelete,
  Edit as IconEdit,
  InfoFilled as IconInfo,
  Picture as IconLib,
  Setting as IconGeneral,
  Brush as IconAppearance,
  Odometer as IconMonitor,
  Bell as IconNotify,
  User as IconUsers,
} from '@element-plus/icons-vue'
import { ELEMENT_ICON_MAP } from '../utils/elementIcons'
import { useSettingsStore } from '../stores/settings'
import { useIconLibraryStore } from '../stores/iconLibrary'
import AccessPanel from '../components/AccessPanel.vue'
import UsersPanel from '../components/UsersPanel.vue'
import NotifyPanel from '../components/NotifyPanel.vue'
import AppearancePanel from '../components/AppearancePanel.vue'
import type { IconItem } from '../api/icons'
import { getHealth } from '../api/health'
import { setLocale, getLocale } from '../locales'
import type { AppLocale } from '../locales'

const { t } = useI18n()
const settingsStore = useSettingsStore()
const iconLibrary = useIconLibraryStore()

type MenuKey = 'general' | 'appearance' | 'apps' | 'icons' | 'access' | 'monitor' | 'notify' | 'usermgmt' | 'about'
const active = ref<MenuKey>('general')
const saving = ref(false)

// ---- 常规设置 ----
const siteName = ref('')
const logoUrl = ref('')
const timezone = ref('system')
const guestMode = ref(false)
const TIMEZONES = [
  'UTC',
  'Asia/Shanghai',
  'Asia/Hong_Kong',
  'Asia/Taipei',
  'Asia/Tokyo',
  'Asia/Singapore',
  'Europe/London',
  'Europe/Berlin',
  'America/New_York',
  'America/Los_Angeles',
]
const langDraft = ref<AppLocale>(getLocale())
const aboutVersion = ref('')

// ---- 应用配置 ----
const tagOptions = ref<string[]>([])
const newTag = ref('')

// ---- 监控设置（采样/推送间隔与保留天数；api-spec §4.4）----
const sampleInterval = ref(60)
const pushInterval = ref(2)
const retentionDays = ref(7)

// ---- 图标库 ----
const iconSearch = ref('')
const favDraft = ref<string[]>([])
interface IconCell {
  kind: 'element' | 'custom'
  key: string // element = 图标名；custom = /icons/ 路径
  name: string
  path?: string
  component?: unknown
  icon: IconItem
}

/** 统一图标库网格：自定义图标置顶（可编辑/删除），其后为内置图标（可切换常用精选） */
const iconCells = computed<IconCell[]>(() => {
  const kw = iconSearch.value.trim().toLowerCase()
  const customs = iconLibrary.icons
    .filter((i) => i.source === 'custom' && (!kw || i.name.toLowerCase().includes(kw)))
    .map((icon) => ({
      kind: 'custom' as const,
      key: icon.path ?? '',
      name: icon.name,
      path: icon.path ?? undefined,
      icon,
    }))
  const elements = iconLibrary.icons
    .filter((i) => i.source === 'builtin' && (!kw || i.name.toLowerCase().includes(kw)))
    .map((icon) => ({
      kind: 'element' as const,
      key: icon.element_name ?? icon.name,
      name: icon.name,
      component: ELEMENT_ICON_MAP[icon.element_name ?? icon.name],
      icon,
    }))
  return [...customs, ...elements]
})

const isFav = (key: string) => favDraft.value.includes(key)

// 自定义图标编辑弹窗
const iconDialog = ref(false)
const iconSaving = ref(false)
const iconForm = ref({
  id: undefined as number | undefined,
  name: '',
  data: '',
  filename: '',
  preview: '',
  element_name: '' as string | null,
})
const iconFileInput = ref<HTMLInputElement>()

onMounted(async () => {
  await Promise.all([settingsStore.load(true), iconLibrary.load(true)])
  siteName.value = settingsStore.siteName
  logoUrl.value = (settingsStore.map['general.logo'] as string) || ''
  timezone.value = (settingsStore.map['general.timezone'] as string) || 'system'
  guestMode.value = settingsStore.map['guest.enabled'] === true
  tagOptions.value = [...settingsStore.tagOptions]
  favDraft.value = [...settingsStore.iconFavorites]
  const map = settingsStore.map
  sampleInterval.value = (map['monitor.sample_interval'] as number) || 60
  pushInterval.value = (map['monitor.push_interval'] as number) || 2
  retentionDays.value = (map['monitor.retention_days'] as number) || 7
  try {
    aboutVersion.value = (await getHealth()).version
  } catch {
    aboutVersion.value = ''
  }
})

function changeLang(v: AppLocale) {
  langDraft.value = v
  setLocale(v)
  save({ 'general.language': v }, t('settings.languageSaved'))
}

function addTag() {
  const tag = newTag.value.trim()
  if (!tag) return
  if (tagOptions.value.includes(tag)) {
    ElMessage.warning(t('settings.tagExists'))
    return
  }
  if (tagOptions.value.length >= 50) {
    ElMessage.warning(t('settings.tagMax'))
    return
  }
  tagOptions.value = [...tagOptions.value, tag]
  newTag.value = ''
}

function removeTag(tag: string) {
  tagOptions.value = tagOptions.value.filter((x) => x !== tag)
}

function toggleFav(key: string) {
  favDraft.value = favDraft.value.includes(key)
    ? favDraft.value.filter((x) => x !== key)
    : [...favDraft.value, key]
  if (favDraft.value.length > 100) {
    favDraft.value = favDraft.value.slice(0, 100)
    ElMessage.warning(t('settings.iconsFavMax'))
  }
}

// ---- 自定义图标 CRUD ----
function openIconCreate() {
  iconForm.value = { id: undefined, name: '', data: '', filename: '', preview: '', element_name: '' }
  iconDialog.value = true
}

function openIconEdit(icon: IconItem) {
  iconForm.value = {
    id: icon.id,
    name: icon.name,
    data: '',
    filename: '',
    preview: icon.path ?? '',
    element_name: icon.element_name ?? '',
  }
  iconDialog.value = true
}

async function removeIcon(icon: IconItem) {
  try {
    await ElMessageBox.confirm(
      t('settings.confirmDeleteIcon', { name: icon.name }),
      t('settings.confirmDeleteIconTitle'),
      { type: 'warning', confirmButtonText: t('settings.deleteBtn') },
    )
  } catch {
    return
  }
  try {
    await iconLibrary.remove(icon.id)
    ElMessage.success(t('settings.iconDeleted'))
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
    ElMessage.warning(t('apps.warnIconSize'))
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
    ElMessage.warning(t('settings.warnIconName'))
    return
  }
  if (!iconForm.value.id && !iconForm.value.data) {
    ElMessage.warning(t('settings.warnPickImage'))
    return
  }
  iconSaving.value = true
  try {
    if (iconForm.value.id) {
      await iconLibrary.update(iconForm.value.id, {
        name: iconForm.value.name.trim(),
        ...(iconForm.value.data ? { data: iconForm.value.data, filename: iconForm.value.filename } : {}),
      })
      ElMessage.success(t('settings.iconUpdated'))
    } else {
      await iconLibrary.create({
        name: iconForm.value.name.trim(),
        data: iconForm.value.data,
        filename: iconForm.value.filename,
      })
      ElMessage.success(t('settings.iconSaved'))
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
    ElMessage.warning(t('settings.warnSiteName'))
    return
  }
  save(
    {
      'general.site_name': siteName.value.trim(),
      'general.logo': logoUrl.value.trim(),
      'general.timezone': timezone.value,
      'guest.enabled': guestMode.value,
    },
    t('settings.generalSaved'),
  )
}

function saveTags() {
  save({ 'apps.tag_options': [...tagOptions.value] }, t('settings.tagsSaved'))
}

function saveIcons() {
  save({ 'apps.icon_favorites': [...favDraft.value] }, t('settings.iconsSaved'))
}

function saveMonitor() {
  if (sampleInterval.value < 10 || pushInterval.value < 1 || retentionDays.value < 1) {
    ElMessage.warning(t('settings.monitorRangeWarn'))
    return
  }
  save(
    {
      'monitor.sample_interval': Math.round(sampleInterval.value),
      'monitor.push_interval': Math.round(pushInterval.value),
      'monitor.retention_days': Math.round(retentionDays.value),
    },
    t('settings.monitorSaved'),
  )
}
</script>

<template>
  <div class="settings-page">
    <!-- 二级菜单 -->
    <aside class="menu glass">
      <div class="menu-title">{{ t('settings.title') }}</div>
      <el-menu :default-active="active" class="menu-list" @select="(k: string) => (active = k as MenuKey)">
        <el-menu-item index="general">
          <el-icon><component :is="IconGeneral" /></el-icon>
          <span>{{ t('settings.menuGeneral') }}</span>
        </el-menu-item>
        <el-menu-item index="appearance">
          <el-icon><component :is="IconAppearance" /></el-icon>
          <span>{{ t('settings.menuAppearance') }}</span>
        </el-menu-item>
        <el-menu-item index="apps">
          <el-icon><component :is="IconApps" /></el-icon>
          <span>{{ t('settings.menuApps') }}</span>
        </el-menu-item>
        <el-menu-item index="icons">
          <el-icon><component :is="IconLib" /></el-icon>
          <span>{{ t('settings.menuIcons') }}</span>
        </el-menu-item>
        <el-menu-item index="access">
          <el-icon><component :is="IconAccess" /></el-icon>
          <span>{{ t('settings.menuAccess') }}</span>
        </el-menu-item>
                <el-menu-item index="monitor">
          <el-icon><component :is="IconMonitor" /></el-icon>
          <span>{{ t('settings.menuMonitor') }}</span>
        </el-menu-item>
        <el-menu-item index="notify">
          <el-icon><component :is="IconNotify" /></el-icon>
          <span>{{ t('settings.menuNotify') }}</span>
        </el-menu-item>
        <el-menu-item index="usermgmt">
          <el-icon><component :is="IconUsers" /></el-icon>
          <span>{{ t('settings.menuUsers') }}</span>
        </el-menu-item>
        <el-menu-item index="about">
          <el-icon><component :is="IconInfo" /></el-icon>
          <span>{{ t('settings.menuAbout') }}</span>
        </el-menu-item>
      </el-menu>
      <p class="menu-hint">{{ t('settings.menuHint') }}</p>
    </aside>

    <!-- 配置面板 -->
    <section class="panel glass">
      <template v-if="active === 'general'">
        <header class="panel-head">
          <h3>{{ t('settings.generalTitle') }}</h3>
          <p>{{ t('settings.generalDesc') }}</p>
        </header>
        <el-form label-position="top" class="panel-body">
                  <el-form-item label="Logo URL">
          <el-input v-model="logoUrl" :placeholder="t('settings.logoUrlPh')" clearable />
        </el-form-item>
        <el-form-item :label="t('settings.timezone')">
          <el-select v-model="timezone" style="max-width: 320px">
            <el-option :label="t('settings.followSystem')" value="system" />
            <el-option v-for="tz in TIMEZONES" :key="tz" :label="tz" :value="tz" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('settings.guestMode')">
          <div class="guest-switch">
            <el-switch v-model="guestMode" />
            <span class="guest-hint">{{ t('settings.guestModeHint') }}</span>
          </div>
        </el-form-item>
<el-form-item :label="t('settings.siteName')" style="max-width: 360px">
            <el-input v-model="siteName" maxlength="64" placeholder="Portal" />
          </el-form-item>
          <el-form-item :label="t('settings.language')" style="max-width: 360px">
            <el-select v-model="langDraft" style="width: 100%" @change="changeLang">
              <el-option label="简体中文" value="zh-CN" />
              <el-option label="English" value="en" />
            </el-select>
          </el-form-item>
          <el-button type="primary" class="btn-gradient" :loading="saving" @click="saveGeneral">
            {{ t('common.save') }}
          </el-button>
        </el-form>
      </template>

      <template v-else-if="active === 'appearance'">
        <AppearancePanel />
      </template>

      <template v-else-if="active === 'apps'">
        <header class="panel-head">
          <h3>{{ t('settings.appsTitle') }}</h3>
          <p>{{ t('settings.appsDesc') }}</p>
        </header>
        <div class="panel-body">
          <div class="tag-editor">
            <el-tag
              v-for="t in tagOptions"
              :key="t"
              closable
              class="tag-item"
              @close="removeTag(t)"
            >
              {{ t }}
            </el-tag>
            <el-input
              v-model="newTag"
              :placeholder="t('settings.tagInputPh')"
              class="tag-input"
              maxlength="32"
              @keyup.enter="addTag"
            >
              <template #append>
                <el-button @click="addTag">{{ t('common.add') }}</el-button>
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
            {{ t('common.save') }}
          </el-button>
        </div>
      </template>

      <template v-else-if="active === 'icons'">
        <header class="panel-head">
          <h3>{{ t('settings.iconsTitle') }}</h3>
          <p>{{ t('settings.iconsDesc') }}</p>
        </header>
        <div class="panel-body icons-body">
          <div class="icons-toolbar">
            <el-input
              v-model="iconSearch"
              :placeholder="t('settings.iconsSearchPh')"
              clearable
              class="icons-search"
            />
            <div class="spacer" />
            <el-button type="primary" class="btn-gradient" @click="openIconCreate">
              {{ t('settings.iconsAdd') }}
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
                :title="t('iconPicker.addToFav', { name: cell.name })"
                @click="toggleFav(cell.key)"
              >
                <img v-if="cell.kind === 'custom'" :src="cell.path" :alt="cell.name" class="im-img" />
                <component v-else :is="cell.component" class="im-svg" />
                <span class="im-name">{{ cell.name }}</span>
              </button>
              <div class="im-ops">
                <button
                  type="button"
                  class="im-op"
                  :title="t('common.edit')"
                  @click.stop="openIconEdit(cell.icon!)"
                >
                  <el-icon :size="11"><IconEdit /></el-icon>
                </button>
                <button
                  type="button"
                  class="im-op danger"
                  :title="t('common.delete')"
                  @click.stop="removeIcon(cell.icon!)"
                >
                  <el-icon :size="11"><IconDelete /></el-icon>
                </button>
              </div>
            </div>
            <div v-if="!iconCells.length" class="im-empty">{{ t('iconPicker.noMatch') }}</div>
          </div>
          <el-button
            type="primary"
            class="btn-gradient"
            :loading="saving"
            style="align-self: flex-start"
            @click="saveIcons"
          >
            {{ t('settings.iconsSave', { n: favDraft.length }) }}
          </el-button>
        </div>


        <!-- 新增/编辑自定义图标 -->
        <el-dialog append-to-body
          v-model="iconDialog"
          :title="iconForm.id ? t('settings.iconDialogEditTitle') : t('settings.iconDialogTitle')"
          width="420px"
          
        >
          <div class="icon-dialog-body">
            <div class="icon-dialog-preview">
              <img v-if="iconForm.preview" :src="iconForm.preview" alt="" />
              <component
                v-else-if="iconForm.element_name && ELEMENT_ICON_MAP[iconForm.element_name]"
                :is="ELEMENT_ICON_MAP[iconForm.element_name]"
                class="im-svg"
              />
              <span v-else>?</span>
            </div>
            <div class="icon-dialog-fields">
              <el-input v-model="iconForm.name" :placeholder="t('settings.iconNamePh')" maxlength="32" />
              <el-button @click="iconFileInput?.click()">
                {{ iconForm.id && !iconForm.data ? t('settings.iconDialogEditBtn') : t('settings.pickImage') }}
              </el-button>
              <input
                ref="iconFileInput"
                type="file"
                accept="image/*"
                hidden
                @change="onIconFile"
              />
              <p class="muted-tip">{{ t('settings.iconFormatTip') }}</p>
            </div>
          </div>
          <template #footer>
            <el-button @click="iconDialog = false">{{ t('common.cancel') }}</el-button>
            <el-button type="primary" class="btn-gradient" :loading="iconSaving" @click="saveIcon">
              {{ t('common.save') }}
            </el-button>
          </template>
        </el-dialog>
      </template>
      <template v-else-if="active === 'access'">
        <AccessPanel />
      </template>
        <template v-else-if="active === 'monitor'">
        <header class="panel-head">
          <h3>{{ t('settings.menuMonitor') }}</h3>
          <p>{{ t('settings.monitorHint') }}</p>
        </header>
        <el-form label-width="auto" class="monitor-form">
          <el-form-item :label="t('settings.sampleInterval')">
            <el-input-number v-model="sampleInterval" :min="10" :max="3600" :step="10" />
            <span class="form-tip">{{ t('settings.sampleIntervalTip') }}</span>
          </el-form-item>
          <el-form-item :label="t('settings.pushInterval')">
            <el-input-number v-model="pushInterval" :min="1" :max="60" :step="1" />
            <span class="form-tip">{{ t('settings.pushIntervalTip') }}</span>
          </el-form-item>
          <el-form-item :label="t('settings.retentionDays')">
            <el-input-number v-model="retentionDays" :min="1" :max="365" :step="1" />
            <span class="form-tip">{{ t('settings.retentionDaysTip') }}</span>
          </el-form-item>
          <el-button type="primary" class="btn-gradient" :loading="saving" @click="saveMonitor">
            {{ t('common.save') }}
          </el-button>
        </el-form>
      </template>
      <template v-else-if="active === 'notify'">
        <header class="panel-head">
          <h3>{{ t('settings.menuNotify') }}</h3>
          <p>{{ t('settings.notifyHint') }}</p>
        </header>
        <NotifyPanel />
      </template>
      <template v-else-if="active === 'usermgmt'">
        <header class="panel-head">
          <h3>{{ t('settings.menuUsers') }}</h3>
          <p>{{ t('settings.usersHint') }}</p>
        </header>
        <UsersPanel />
      </template>
      <template v-else-if="active === 'about'">
          <header class="panel-head">
            <h3>{{ t('settings.aboutTitle') }}</h3>
            <p>Portal · {{ t('home.copyright') }}</p>
          </header>
          <div class="panel-body about-body">
            <div class="about-row">
              <span class="muted-tip">{{ t('settings.version') }}</span>
              <b>Portal {{ aboutVersion || '—' }}</b>
            </div>
            <div class="about-row">
              <span class="muted-tip">{{ t('settings.storageMode') }}</span>
              <b>SQLite</b>
            </div>
          </div>
        </template>
    </section>
  </div>
</template>

<style scoped>
.guest-switch {
  display: flex;
  align-items: center;
  gap: 10px;
}
.guest-hint {
  font-size: 12.5px;
  color: var(--p-muted);
}
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
.about-body {
  max-width: 480px;
}
.about-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px dashed var(--p-card-border);
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
  background: var(--p-card);
  transition: border-color 0.12s, background 0.12s;
}
.im-cell:hover {
  border-color: var(--p-primary);
}
.im-cell.active {
  background: color-mix(in srgb, var(--p-primary) 8%, transparent);
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
  background: color-mix(in srgb, var(--p-primary) 18%, transparent);
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

.panel-hint {
  margin: 0 0 14px;
  font-size: 12.5px;
  color: var(--p-muted);
}
.monitor-form .form-tip {
  margin-left: 10px;
  font-size: 12px;
  color: var(--p-muted);
}
</style>
