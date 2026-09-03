<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useI18n } from 'vue-i18n'
import {
  Download as IconExport,
  Plus as IconPlus,
  Setting as IconSetting,
  Upload as IconImport,
} from '@element-plus/icons-vue'
import { portalApi } from '../api/portal'
import { usersApi } from '../api/users'
import type {
  AccessType,
  Category,
  HealthType,
  IconType,
  OpenMode,
  PortalApp,
  Visibility,
} from '../api/portal'
import { useAuthStore } from '../stores/auth'
import { useSettingsStore } from '../stores/settings'
import AppIcon from '../components/AppIcon.vue'
import IconPicker from '../components/IconPicker.vue'
import EntryPopup from '../components/EntryPopup.vue'
import type { IconPick } from '../components/IconPicker.vue'
import { makeExportFilename } from '../utils/export'

const auth = useAuthStore()
const settingsStore = useSettingsStore()
const { t } = useI18n()
const isAdmin = computed(() => auth.isAdmin)

// ============ 列表与过滤 ============
const categories = ref<Category[]>([])
const apps = ref<PortalApp[]>([])
const loading = ref(false)
const keyword = ref('')
const categoryFilter = ref<number | null>(null)

async function loadCategories() {
  categories.value = await portalApi.listCategories()
}

async function loadApps() {
  apps.value = await portalApi.listApps()
}

async function loadAll() {
  loading.value = true
  try {
    await Promise.all([loadCategories(), loadApps()])
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  settingsStore.load()
  loadAll()
})

const filtered = computed(() => {
  let list = apps.value
  if (categoryFilter.value != null) {
    list = list.filter((a) => a.category_id === categoryFilter.value)
  }
  const kw = keyword.value.trim().toLowerCase()
  if (kw) {
    list = list.filter(
      (a) =>
        a.name.toLowerCase().includes(kw) ||
        a.description.toLowerCase().includes(kw) ||
        a.tags.some((t) => t.toLowerCase().includes(kw)),
    )
  }
  return list
})

const catName = (id: number | null) =>
  categories.value.find((c) => c.id === id)?.name ?? t('apps.uncategorized')

const ACCESS_LABEL = computed<Record<AccessType, string>>(() => ({
  domain: t('apps.urlType.domain'),
  lan: t('apps.urlType.lan'),
  ssh: t('apps.urlType.ssh'),
  vpn: t('apps.urlType.vpn'),
  custom: t('apps.urlType.custom'),
}))

// ============ 多入口选择浮层（M04-12；dev-plan P3.8）============
const entryPopupOpen = ref(false)
const entryPopupApp = ref<PortalApp | null>(null)

function openEntryPopup(app: PortalApp) {
  if (!app.urls.length) return
  entryPopupApp.value = app
  entryPopupOpen.value = true
}

function chooseEntryUrl(app: PortalApp, url: string) {
  if (app.open_mode === 'current') window.location.href = url
  else window.open(url, '_blank', 'noopener')
}

const VISIBILITY_LABEL = computed<Record<Visibility, string>>(() => ({
  all: t('apps.visibility.all'),
  admin: t('apps.visibility.admin'),
  users: t('apps.visibility.users'),
  public: t('apps.visibility.public'),
}))
const OPEN_LABEL = computed<Record<OpenMode, string>>(() => ({
  newtab: t('apps.openMode.newtab'),
  current: t('apps.openMode.current'),
  iframe: t('apps.openMode.iframe'),
}))

// ============ 应用编辑抽屉 ============
const drawer = ref(false)
const saving = ref(false)

interface UrlDraft {
  key: number
  id?: number
  access_type: AccessType
  url: string
  label: string
}

const draft = ref({
  id: undefined as number | undefined,
  name: '',
  description: '',
  category_id: null as number | null,
  icon: '',
  icon_type: 'url' as IconType,
  open_mode: 'newtab' as OpenMode,
  visibility: 'all' as Visibility,
  visible_users: [] as number[],
  enabled: true,
  health_type: '' as HealthType,
  health_target: '',
  health_interval: 60,
  tags: [] as string[],
  remark: '',
  doc_url: '',
})
const urlRows = ref<UrlDraft[]>([])
const removedUrlIds = ref<number[]>([])
let urlKey = 1

function openCreate() {
  void loadUserOptions()
  draft.value = {
    id: undefined,
    visible_users: [],
    name: '',
    description: '',
    category_id: null,
    icon: '',
    icon_type: 'url',
    open_mode: 'newtab',
    visibility: 'all',
    enabled: true,
    health_type: '',
    health_target: '',
    health_interval: 60,
    tags: [],
    remark: '',
    doc_url: '',
  }
  urlRows.value = []
  removedUrlIds.value = []
  faviconSource.value = ''
  drawer.value = true
}

function openEdit(app: PortalApp) {
  void loadUserOptions()
  draft.value = {
    id: app.id,
    name: app.name,
    description: app.description,
    category_id: app.category_id,
    icon: app.icon ?? '',
    icon_type: app.icon_type,
    open_mode: app.open_mode,
    visibility: app.visibility,
    visible_users: app.visible_users ?? [],
    enabled: app.enabled,
    health_type: app.health_type,
    health_target: app.health_target ?? '',
    health_interval: app.health_interval,
    tags: [...app.tags],
    remark: app.remark,
    doc_url: app.doc_url ?? '',
  }
  urlRows.value = app.urls.map((u) => ({
    key: urlKey++,
    id: u.id,
    access_type: u.access_type,
    url: u.url,
    label: u.label,
  }))
  removedUrlIds.value = []
  faviconSource.value = ''
  drawer.value = true
}

function addUrlRow() {
  urlRows.value.push({ key: urlKey++, access_type: 'lan', url: '', label: '' })
}

function removeUrlRow(index: number) {
  const row = urlRows.value[index]
  if (row.id) removedUrlIds.value.push(row.id)
  urlRows.value.splice(index, 1)
}

function moveUrlRow(index: number, dir: -1 | 1) {
  const target = index + dir
  if (target < 0 || target >= urlRows.value.length) return
  const rows = [...urlRows.value]
  ;[rows[index], rows[target]] = [rows[target], rows[index]]
  urlRows.value = rows
}

async function saveApp() {
  if (!draft.value.name.trim()) {
    ElMessage.warning(t('apps.warnName'))
    return
  }
  if (urlRows.value.some((r) => !r.url.trim())) {
    ElMessage.warning(t('apps.warnUrl'))
    return
  }
  saving.value = true
  try {
    const payload = {
      name: draft.value.name.trim(),
      description: draft.value.description.trim(),
      category_id: draft.value.category_id,
      icon: draft.value.icon || null,
      icon_type: draft.value.icon_type,
      open_mode: draft.value.open_mode,
      visibility: draft.value.visibility,
      enabled: draft.value.enabled,
      health_type: draft.value.health_type,
      health_target: draft.value.health_target.trim() || null,
      health_interval: draft.value.health_interval,
      visible_users: draft.value.visible_users,
      tags: [...draft.value.tags],
      remark: draft.value.remark,
      doc_url: draft.value.doc_url.trim() || null,
    }
    let appId = draft.value.id
    if (appId) {
      await portalApi.updateApp(appId, payload)
    } else {
      appId = (await portalApi.createApp(payload)).id
    }
    for (const id of removedUrlIds.value) await portalApi.deleteUrl(id)
    for (const [i, row] of urlRows.value.entries()) {
      const body = {
        access_type: row.access_type,
        url: row.url.trim(),
        label: row.label.trim(),
        sort: i + 1,
      }
      if (row.id) await portalApi.updateUrl(row.id, body)
      else await portalApi.createUrl(appId, body)
    }
    ElMessage.success(draft.value.id ? t('apps.saved') : t('apps.created'))
    drawer.value = false
    await loadApps()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(app: PortalApp) {
  try {
    await portalApi.updateApp(app.id, { enabled: app.enabled })
  } catch (e) {
    app.enabled = !app.enabled
    ElMessage.error((e as Error).message)
  }
}

async function removeApp(app: PortalApp) {
  try {
    await ElMessageBox.confirm(t('apps.confirmRecycle', { name: app.name }), t('apps.confirmRecycleTitle'), {
      type: 'warning',
      confirmButtonText: t('apps.recycleBtn'),
    })
  } catch {
    return
  }
  try {
    await portalApi.deleteApp(app.id)
    ElMessage.success(t('apps.recycled'))
    await loadApps()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

// ============ 图标（URL / 上传 / Emoji + favicon 抓取）============
const faviconSource = ref('')
const userOptions = ref<{ id: number; username: string }[]>([])
async function loadUserOptions() {
  try {
    const data = await usersApi.list('', 1, 100)
    userOptions.value = data.items.map((u) => ({ id: u.id, username: u.username }))
  } catch {
    userOptions.value = []
  }
}
const iconFileInput = ref<HTMLInputElement>()

async function onIconFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (file.size > 2 * 1024 * 1024) {
    ElMessage.warning(t('apps.warnIconSize'))
    return
  }
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = () => reject(new Error(t('apps.readJsonFail')))
    reader.readAsDataURL(file)
  })
  try {
    const { url } = await portalApi.uploadIcon(file.name, dataUrl.split(',')[1] ?? '')
    draft.value.icon = url
    draft.value.icon_type = 'upload'
    ElMessage.success(t('apps.iconUploaded'))
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function grabFavicon() {
  const site = faviconSource.value.trim()
  if (!site) {
    ElMessage.warning(t('apps.faviconNeedSite'))
    return
  }
  try {
    const { url } = await portalApi.fetchFavicon(site)
    draft.value.icon = url
    draft.value.icon_type = 'upload'
    ElMessage.success(t('apps.faviconOk'))
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

/** 图标库选中：element 写图标名，custom 写 /icons/ 路径并切到 upload 类型 */
/** 切换图标来源 tab：清空已选图标（不同来源的值不通用，避免预览碎图） */
function switchIconType(type: string | number | boolean | undefined) {
  draft.value.icon_type = type as IconType
  draft.value.icon = ''
}

function pickAppIcon(sel: IconPick) {
  draft.value.icon = sel.value
  if (sel.value) {
    draft.value.icon_type = sel.kind === 'custom' ? 'upload' : 'element'
  }
}

// ============ 分组管理 ============
const catDialog = ref(false)
const catSaving = ref(false)
const catForm = ref({
  id: undefined as number | undefined,
  name: '',
  icon: '',
  icon_type: 'element' as string | null,
})

function pickCatIcon(sel: IconPick) {
  catForm.value.icon = sel.value
  // element → 图标名；custom → /icons/ 路径（upload 类型）
  catForm.value.icon_type = sel.value ? (sel.kind === 'custom' ? 'upload' : 'element') : catForm.value.icon_type
}

function openCatCreate() {
  catForm.value = { id: undefined, name: '', icon: '', icon_type: 'element' }
  catDialog.value = true
}

function openCatEdit(cat: Category) {
  catForm.value = {
    id: cat.id,
    name: cat.name,
    icon: cat.icon ?? '',
    icon_type: cat.icon_type ?? 'emoji',
  }
  catDialog.value = true
}

async function saveCategory() {
  if (!catForm.value.name.trim()) {
    ElMessage.warning(t('apps.warnCatName'))
    return
  }
  catSaving.value = true
  try {
    const payload = {
      name: catForm.value.name.trim(),
      icon: catForm.value.icon || null,
      icon_type: catForm.value.icon ? 'element' : catForm.value.icon_type,
    }
    if (catForm.value.id) await portalApi.updateCategory(catForm.value.id, payload)
    else await portalApi.createCategory(payload)
    catDialog.value = false
    ElMessage.success(t('apps.catSaved'))
    await loadCategories()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    catSaving.value = false
  }
}

async function removeCategory(cat: Category) {
  try {
    await ElMessageBox.confirm(
      t('apps.confirmDeleteCat', { name: cat.name, n: cat.app_count }),
      t('apps.confirmDeleteCatTitle'),
      { type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await portalApi.deleteCategory(cat.id)
    ElMessage.success(t('apps.catDeleted'))
    await Promise.all([loadCategories(), loadApps()])
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function moveCategory(cat: Category, dir: -1 | 1) {
  const list = [...categories.value].sort((a, b) => a.sort - b.sort || a.id - b.id)
  const idx = list.findIndex((c) => c.id === cat.id)
  const target = idx + dir
  if (target < 0 || target >= list.length) return
  ;[list[idx], list[target]] = [list[target], list[idx]]
  await portalApi.sortCategories(list.map((c, i) => ({ id: c.id, sort: i })))
  await loadCategories()
}

// ============ 导入 / 导出 ============
const importInput = ref<HTMLInputElement>()

async function onImportFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  let payload: unknown
  try {
    payload = JSON.parse(await file.text())
  } catch {
    ElMessage.error(t('apps.importBadJson'))
    return
  }
  const counts = payload as { apps?: unknown[]; categories?: unknown[] }
  try {
    await ElMessageBox.confirm(
      t('apps.importConfirm', {
        apps: apps.value.length,
        cats: categories.value.length,
        nApps: counts.apps?.length ?? 0,
        nCats: counts.categories?.length ?? 0,
      }),
      t('apps.importTitle'),
      { type: 'warning', confirmButtonText: t('apps.importBtn') },
    )
  } catch {
    return
  }
  try {
    const r = await portalApi.importApps(payload)
    ElMessage.success(
      t('apps.importOk', { apps: r.apps, cats: r.categories, urls: r.urls }),
    )
    await loadAll()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function doExport() {
  try {
    const data = await portalApi.exportApps()
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = makeExportFilename('portal-apps', 'json')
    a.click()
    URL.revokeObjectURL(a.href)
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}
</script>

<template>
  <div class="apps-page">
    <!-- 工具栏 -->
    <section class="toolbar glass">
      <el-input v-model="keyword" :placeholder="t('apps.searchPh')" clearable class="search" />
      <el-select
        v-model="categoryFilter"
        :placeholder="t('apps.allCategories')"
        clearable
        class="cat-filter"
        @clear="categoryFilter = null"
      >
        <el-option :label="t('apps.uncategorized')" :value="-1" />
        <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
      </el-select>
      <div class="spacer" />
      <template v-if="isAdmin">
        <el-button :icon="IconSetting" @click="openCatCreate()">{{ t('apps.catManage') }}</el-button>
        <el-button :icon="IconImport" @click="importInput?.click()">{{ t('apps.import') }}</el-button>
        <el-button :icon="IconExport" @click="doExport">{{ t('apps.export') }}</el-button>
        <el-button type="primary" class="btn-gradient" :icon="IconPlus" @click="openCreate">
          {{ t('apps.createApp') }}
        </el-button>
      </template>
      <input
        ref="importInput"
        type="file"
        accept="application/json,.json"
        hidden
        @change="onImportFile"
      />
    </section>

    <!-- 应用列表 -->
    <section class="table-card glass">
      <el-table :data="filtered" v-loading="loading" style="width: 100%">
        <el-table-column :label="t('apps.thIcon')" width="72" align="center">
          <template #default="{ row }">
            <div class="app-icon">
              <AppIcon :icon="row.icon" :icon-type="row.icon_type" :size="26" />
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('apps.thApp')" min-width="200">
          <template #default="{ row }">
            <b>{{ row.name }}</b>
            <p class="desc">{{ row.description || '—' }}</p>
          </template>
        </el-table-column>
        <el-table-column :label="t('apps.thCategory')" width="120">
          <template #default="{ row }">{{ catName(row.category_id) }}</template>
        </el-table-column>
        <el-table-column :label="t('apps.thUrls')" min-width="200">
          <template #default="{ row }">
            <div class="urls">
              <el-tag
                v-for="u in row.urls"
                :key="u.id"
                size="small"
                class="url-tag clickable"
                :type="u.access_type === 'domain' ? 'primary' : u.access_type === 'lan' ? 'success' : 'info'"
                :title="t('entry.pickTitle')"
                @click="openEntryPopup(row)"
              >
                {{ ACCESS_LABEL[u.access_type as AccessType] }}·{{ u.label || u.url }}
              </el-tag>
              <span v-if="!row.urls.length" class="muted">{{ t('apps.noEntry') }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('apps.thOpenMode')" width="100">
          <template #default="{ row }">{{ OPEN_LABEL[row.open_mode as OpenMode] }}</template>
        </el-table-column>
        <el-table-column :label="t('apps.thVisibility')" width="110">
          <template #default="{ row }">{{ VISIBILITY_LABEL[row.visibility as Visibility] }}</template>
        </el-table-column>
        <el-table-column v-if="isAdmin" :label="t('apps.thEnabled')" width="80">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" @change="toggleEnabled(row)" />
          </template>
        </el-table-column>
        <el-table-column v-if="isAdmin" :label="t('apps.thActions')" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
            <el-button link type="danger" @click="removeApp(row)">{{ t('common.delete') }}</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :description="t('apps.emptyTip')" />
        </template>
      </el-table>
    </section>

    <!-- 应用编辑抽屉 -->
    <el-drawer
      v-model="drawer"
      :title="draft.id ? t('apps.editApp') : t('apps.createApp')"
      size="620px"
      destroy-on-close
      append-to-body
    >
      <div class="drawer-body">
        <el-form label-position="top">
          <el-form-item :label="t('apps.fieldName')" required>
            <el-input v-model="draft.name" :placeholder="t('apps.fieldNamePh')" maxlength="128" />
          </el-form-item>
          <el-form-item :label="t('apps.fieldDesc')">
            <el-input v-model="draft.description" :placeholder="t('apps.fieldDescPh')" maxlength="512" />
          </el-form-item>
          <el-form-item :label="t('apps.fieldCategory')">
            <el-select
              v-model="draft.category_id"
              :placeholder="t('apps.uncategorized')"
              clearable
              style="width: 100%"
              @clear="draft.category_id = null"
            >
              <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </el-form-item>

          <el-form-item :label="t('apps.fieldIcon')">
            <div class="icon-editor">
              <div class="icon-editor-head">
                <el-radio-group :model-value="draft.icon_type" @change="switchIconType">
                  <el-radio-button value="url">{{ t('apps.iconUrl') }}</el-radio-button>
                  <el-radio-button value="upload">{{ t('apps.iconUpload') }}</el-radio-button>
                  <el-radio-button value="element">{{ t('apps.iconLibrary') }}</el-radio-button>
                </el-radio-group>
                <div class="icon-preview">
                  <AppIcon :icon="draft.icon" :icon-type="draft.icon_type" :size="32" />
                </div>
              </div>
              <template v-if="draft.icon_type === 'url'">
                <el-input v-model="draft.icon" :placeholder="t('apps.iconUrlPh')" />
                <div class="favicon-row">
                  <el-input v-model="faviconSource" :placeholder="t('apps.faviconPh')" />
                  <el-button @click="grabFavicon">{{ t('apps.faviconBtn') }}</el-button>
                </div>
              </template>
              <template v-else-if="draft.icon_type === 'upload'">
                <el-button @click="iconFileInput?.click()">{{ t('apps.uploadBtn') }}</el-button>
                <input ref="iconFileInput" type="file" accept="image/*" hidden @change="onIconFile" />
              </template>
              <template v-else>
                <IconPicker
                  :model-value="draft.icon"
                  :max-height="200"
                  @select="pickAppIcon"
                />
              </template>
            </div>
          </el-form-item>

          <el-form-item :label="t('apps.fieldUrls')">
            <div class="url-editor">
              <div v-for="(row, i) in urlRows" :key="row.key" class="url-row">
                <el-select v-model="row.access_type" class="url-type">
                  <el-option :label="t('apps.urlType.domain')" value="domain" />
                  <el-option :label="t('apps.urlType.lan')" value="lan" />
                  <el-option :label="t('apps.urlType.ssh')" value="ssh" />
                  <el-option :label="t('apps.urlType.vpn')" value="vpn" />
                  <el-option :label="t('apps.urlType.custom')" value="custom" />
                </el-select>
                <el-input v-model="row.url" :placeholder="t('apps.urlAddressPh')" />
                <el-input v-model="row.label" :placeholder="t('apps.urlLabelPh')" class="url-label" maxlength="64" />
                <div class="url-ops">
                  <el-button link :disabled="i === 0" @click="moveUrlRow(i, -1)">↑</el-button>
                  <el-button
                    link
                    :disabled="i === urlRows.length - 1"
                    @click="moveUrlRow(i, 1)"
                  >
                    ↓
                  </el-button>
                  <el-button link type="danger" @click="removeUrlRow(i)">✕</el-button>
                </div>
              </div>
              <el-button plain class="add-url" @click="addUrlRow">{{ t('apps.addUrl') }}</el-button>
            </div>
          </el-form-item>

          <!-- 探活配置（M07-1；P6） -->
          <el-form-item :label="t('home.probeTitle')">
            <div class="probe-editor">
              <el-select v-model="draft.health_type" class="probe-type" style="width: 150px">
                <el-option :label="t('home.probeTypeNone')" value="" />
                <el-option :label="t('home.probeTypeHttp')" value="http" />
                <el-option :label="t('home.probeTypeTcp')" value="tcp" />
                <el-option :label="t('home.probeTypeKeyword')" value="keyword" />
              </el-select>
              <el-input
                v-model="draft.health_target"
                :placeholder="draft.health_type === 'keyword' ? t('home.probeTargetKeyword') : t('home.probeTargetHttp')"
                :disabled="!draft.health_type"
                class="probe-target"
              />
              <el-input-number
                v-model="draft.health_interval"
                :min="10"
                :max="3600"
                :step="10"
                :disabled="!draft.health_type"
                style="width: 120px"
              />
              <span class="probe-unit">{{ t('home.probeInterval') }}</span>
            </div>
          </el-form-item>

          <div class="form-grid">
            <el-form-item :label="t('apps.fieldOpenMode')">
              <el-select v-model="draft.open_mode" style="width: 100%">
                <el-option :label="t('apps.openMode.newtab')" value="newtab" />
                <el-option :label="t('apps.openMode.current')" value="current" />
                <el-option :label="t('apps.openMode.iframe')" value="iframe" />
              </el-select>
            </el-form-item>
            <el-form-item :label="t('apps.fieldVisibility')">
              <div style="width: 100%">
                <el-select v-model="draft.visibility" style="width: 100%">
                  <el-option :label="t('apps.visibility.all')" value="all" />
                  <el-option :label="t('apps.visibility.users')" value="users" />
                  <el-option :label="t('apps.visibility.admin')" value="admin" />
                  <el-option :label="t('apps.visibility.public')" value="public" />
                </el-select>
                <el-select
                  v-if="draft.visibility === 'users'"
                  v-model="draft.visible_users"
                  multiple
                  filterable
                  :placeholder="t('apps.visibleUsersPh')"
                  style="width: 100%; margin-top: 8px"
                >
                  <el-option
                    v-for="u in userOptions"
                    :key="u.id"
                    :label="u.username"
                    :value="u.id"
                  />
                </el-select>
              </div>
            </el-form-item>
            <el-form-item :label="t('apps.fieldHealthType')">
              <el-select v-model="draft.health_type" style="width: 100%">
                <el-option :label="t('apps.healthType.none')" value="" />
                <el-option :label="t('apps.healthType.http')" value="http" />
                <el-option :label="t('apps.healthType.tcp')" value="tcp" />
                <el-option :label="t('apps.healthType.keyword')" value="keyword" />
              </el-select>
            </el-form-item>
            <el-form-item :label="t('apps.fieldHealthTarget')">
              <el-input
                v-model="draft.health_target"
                :placeholder="t('apps.healthTargetPh')"
                :disabled="!draft.health_type"
              />
            </el-form-item>
          </div>

          <el-form-item :label="t('apps.fieldTags')">
            <el-select
              v-model="draft.tags"
              multiple
              :multiple-limit="6"
              :placeholder="t('apps.tagsPh')"
              style="width: 100%"
            >
              <el-option v-for="tag in settingsStore.tagOptions" :key="tag" :label="tag" :value="tag" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('apps.fieldRemark')">
            <el-input v-model="draft.remark" type="textarea" :rows="2" :placeholder="t('apps.remarkPh')" />
          </el-form-item>
          <el-form-item :label="t('apps.fieldDocUrl')">
            <el-input v-model="draft.doc_url" :placeholder="t('apps.fieldDocUrlPh')" />
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="drawer = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" class="btn-gradient" :loading="saving" @click="saveApp">
          {{ t('common.save') }}
        </el-button>
      </template>
    </el-drawer>

    <!-- 分组管理弹窗 -->
    <el-dialog v-model="catDialog" :title="t('apps.catDialogTitle')" width="560px" append-to-body>
      <div class="cat-list">
        <div v-for="c in categories" :key="c.id" class="cat-row">
          <span class="cat-icon">
            <AppIcon :icon="c.icon" :icon-type="c.icon_type ?? 'emoji'" :size="18" />
          </span>
          <b>{{ c.name }}</b>
          <span class="muted">{{ t('apps.catCount', { n: c.app_count }) }}</span>
          <div class="cat-ops">
            <el-button link @click="moveCategory(c, -1)">↑</el-button>
            <el-button link @click="moveCategory(c, 1)">↓</el-button>
            <el-button link type="primary" @click="openCatEdit(c)">{{ t('common.edit') }}</el-button>
            <el-button link type="danger" @click="removeCategory(c)">{{ t('common.delete') }}</el-button>
          </div>
        </div>
        <el-empty v-if="!categories.length" :description="t('apps.catEmpty')" :image-size="72" />
      </div>
      <el-divider />
      <div class="cat-form">
        <el-input v-model="catForm.name" :placeholder="t('apps.catNamePh')" maxlength="64" />
        <el-button
          v-if="catForm.id"
          :loading="catSaving"
          type="primary"
          @click="saveCategory"
        >
          {{ t('apps.catSaveEdit') }}
        </el-button>
        <el-button
          v-else
          :loading="catSaving"
          type="primary"
          class="btn-gradient"
          @click="saveCategory"
        >
          {{ t('apps.catCreate') }}
        </el-button>
        <el-button v-if="catForm.id" @click="openCatCreate">{{ t('apps.catCancelEdit') }}</el-button>
      </div>
      <div class="cat-picker">
        <div class="cat-picker-label">
          {{ t('apps.catPickerLabel', { name: catForm.icon || t('apps.catPickerNone') }) }}
        </div>
        <IconPicker :model-value="catForm.icon" :max-height="170" @select="pickCatIcon" />
      </div>
    </el-dialog>

    <!-- 多入口选择浮层（M04-12）：点击入口标签打开，按当前环境优先级排序 -->
    <EntryPopup v-model="entryPopupOpen" :app="entryPopupApp" @choose="chooseEntryUrl" />
  </div>
</template>

<style scoped>
.apps-page {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: clamp(10px, 1.4vw, 14px);
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  flex-wrap: wrap;
  flex-shrink: 0;
}
.search {
  width: min(320px, 100%);
}
.cat-filter {
  width: 160px;
}
.spacer {
  flex: 1;
}
.table-card {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 6px 10px 10px;
}
.app-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--p-primary) 6%, transparent);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  overflow: hidden;
  margin: 0 auto;
}
.app-icon img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.app-icon .app-icon__el {
  color: var(--p-primary);
}
.desc {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--p-muted);
}
.urls {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.url-tag {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.url-tag.clickable {
  cursor: pointer;
}
.muted {
  color: var(--p-muted);
  font-size: 12px;
}

/* 抽屉 */
.drawer-body {
  padding-right: 6px;
}
.icon-editor {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.icon-editor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.icon-preview {
  width: 52px;
  height: 52px;
  flex-shrink: 0;
  border-radius: 12px;
  border: 1px dashed var(--p-card-border);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26px;
  overflow: hidden;
}
.icon-preview img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.favicon-row {
  display: flex;
  gap: 8px;
}
.url-editor {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.url-row {
  display: flex;
  gap: 6px;
  align-items: center;
}
.url-type {
  width: 108px;
  flex-shrink: 0;
}
.url-label {
  width: 110px;
  flex-shrink: 0;
}
.url-ops {
  display: flex;
  flex-shrink: 0;
}
.url-ops .el-button + .el-button {
  margin-left: 2px;
}
.add-url {
  align-self: flex-start;
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  column-gap: 14px;
}
@media (max-width: 600px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
  .url-row {
    flex-wrap: wrap;
  }
  .url-type,
  .url-label {
    width: 100%;
  }
}

/* 分组管理 */
.cat-list {
  max-height: 320px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.cat-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--p-card-border);
  border-radius: 10px;
}
.cat-icon {
  font-size: 18px;
  display: flex;
  align-items: center;
  color: var(--p-primary);
}
.cat-ops {
  margin-left: auto;
  display: flex;
}
.cat-ops .el-button + .el-button {
  margin-left: 2px;
}
.cat-form {
  display: flex;
  gap: 8px;
}
.cat-picker {
  margin-top: 12px;
}
.cat-picker-label {
  font-size: 12px;
  color: var(--p-muted);
  margin-bottom: 8px;
}
</style>
