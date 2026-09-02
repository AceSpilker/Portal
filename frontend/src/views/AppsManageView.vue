<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Download as IconExport,
  Plus as IconPlus,
  Setting as IconSetting,
  Upload as IconImport,
} from '@element-plus/icons-vue'
import { portalApi } from '../api/portal'
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
import { isMobile } from '../composables/useIsMobile'

const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role === 'admin')

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

onMounted(loadAll)

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
  categories.value.find((c) => c.id === id)?.name ?? '未分组'

const ACCESS_LABEL: Record<AccessType, string> = {
  domain: '域名',
  lan: '内网',
  ssh: 'SSH',
  vpn: 'VPN',
  custom: '自定义',
}
const VISIBILITY_LABEL: Record<Visibility, string> = {
  all: '所有人',
  admin: '仅管理员',
  users: '指定用户',
}
const OPEN_LABEL: Record<OpenMode, string> = {
  newtab: '新标签',
  current: '当前页',
  iframe: '内嵌',
}
const EMOJIS = ['🎬', '📺', '📥', '🏠', '🔧', '🌐', '🎵', '📷', '⚙️', '🛠️', '📚', '💡', '🔔', '📁', '🗂️', '🖥️', '📱', '🐳', '⭐', '🔥']

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
  enabled: true,
  health_type: '' as HealthType,
  health_target: '',
  health_interval: 60,
  tags: '',
  remark: '',
  doc_url: '',
})
const urlRows = ref<UrlDraft[]>([])
const removedUrlIds = ref<number[]>([])
let urlKey = 1

function openCreate() {
  draft.value = {
    id: undefined,
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
    tags: '',
    remark: '',
    doc_url: '',
  }
  urlRows.value = []
  removedUrlIds.value = []
  faviconSource.value = ''
  drawer.value = true
}

function openEdit(app: PortalApp) {
  draft.value = {
    id: app.id,
    name: app.name,
    description: app.description,
    category_id: app.category_id,
    icon: app.icon ?? '',
    icon_type: app.icon_type,
    open_mode: app.open_mode,
    visibility: app.visibility,
    enabled: app.enabled,
    health_type: app.health_type,
    health_target: app.health_target ?? '',
    health_interval: app.health_interval,
    tags: app.tags.join(', '),
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
    ElMessage.warning('请填写应用名称')
    return
  }
  if (urlRows.value.some((r) => !r.url.trim())) {
    ElMessage.warning('存在未填写地址的访问入口')
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
      tags: draft.value.tags
        .split(/[,，]/)
        .map((s) => s.trim())
        .filter(Boolean),
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
    ElMessage.success(draft.value.id ? '应用已保存' : '应用已创建')
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
    await ElMessageBox.confirm(`确定将「${app.name}」移入回收站？`, '删除应用', {
      type: 'warning',
      confirmButtonText: '移入回收站',
    })
  } catch {
    return
  }
  try {
    await portalApi.deleteApp(app.id)
    ElMessage.success('已移入回收站')
    await loadApps()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

// ============ 图标（URL / 上传 / Emoji + favicon 抓取）============
const faviconSource = ref('')
const iconFileInput = ref<HTMLInputElement>()

async function onIconFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (file.size > 2 * 1024 * 1024) {
    ElMessage.warning('图标文件不能超过 2MB')
    return
  }
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = () => reject(new Error('读取文件失败'))
    reader.readAsDataURL(file)
  })
  try {
    const { url } = await portalApi.uploadIcon(file.name, dataUrl.split(',')[1] ?? '')
    draft.value.icon = url
    draft.value.icon_type = 'upload'
    ElMessage.success('图标已上传')
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function grabFavicon() {
  const site = faviconSource.value.trim()
  if (!site) {
    ElMessage.warning('请先填写目标站地址（如 https://jf.example.com）')
    return
  }
  try {
    const { url } = await portalApi.fetchFavicon(site)
    draft.value.icon = url
    draft.value.icon_type = 'upload'
    ElMessage.success('已抓取目标站图标')
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

// ============ 分组管理 ============
const catDialog = ref(false)
const catSaving = ref(false)
const catForm = ref({ id: undefined as number | undefined, name: '', icon: '' })

function openCatCreate() {
  catForm.value = { id: undefined, name: '', icon: '' }
  catDialog.value = true
}

function openCatEdit(cat: Category) {
  catForm.value = { id: cat.id, name: cat.name, icon: cat.icon ?? '' }
  catDialog.value = true
}

async function saveCategory() {
  if (!catForm.value.name.trim()) {
    ElMessage.warning('请填写分组名')
    return
  }
  catSaving.value = true
  try {
    const payload = { name: catForm.value.name.trim(), icon: catForm.value.icon || null }
    if (catForm.value.id) await portalApi.updateCategory(catForm.value.id, payload)
    else await portalApi.createCategory(payload)
    catDialog.value = false
    ElMessage.success('分组已保存')
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
      `删除分组「${cat.name}」后，组内 ${cat.app_count} 个应用将移出分组（不删除）。确定？`,
      '删除分组',
      { type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await portalApi.deleteCategory(cat.id)
    ElMessage.success('分组已删除')
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
    ElMessage.error('文件不是有效的 JSON')
    return
  }
  const counts = payload as { apps?: unknown[]; categories?: unknown[] }
  try {
    await ElMessageBox.confirm(
      `导入为覆盖式：现有 ${apps.value.length} 个应用、${categories.value.length} 个分组将被文件内容替换（应用 ${counts.apps?.length ?? 0}、分组 ${counts.categories?.length ?? 0}）。确定继续？`,
      '覆盖导入确认',
      { type: 'warning', confirmButtonText: '导入' },
    )
  } catch {
    return
  }
  try {
    const r = await portalApi.importApps(payload)
    ElMessage.success(`已导入 ${r.apps} 个应用、${r.categories} 个分组、${r.urls} 个入口`)
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
    a.download = `portal-apps-${new Date().toISOString().slice(0, 10)}.json`
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
      <el-input v-model="keyword" placeholder="搜索名称 / 描述 / 标签" clearable class="search" />
      <el-select
        v-model="categoryFilter"
        placeholder="全部分组"
        clearable
        class="cat-filter"
        @clear="categoryFilter = null"
      >
        <el-option label="未分组" :value="-1" />
        <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
      </el-select>
      <div class="spacer" />
      <template v-if="isAdmin">
        <el-button :icon="IconSetting" @click="openCatCreate()">分组管理</el-button>
        <el-button :icon="IconImport" @click="importInput?.click()">导入</el-button>
        <el-button :icon="IconExport" @click="doExport">导出</el-button>
        <el-button type="primary" class="btn-gradient" :icon="IconPlus" @click="openCreate">
          新建应用
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
        <el-table-column label="图标" width="72" align="center">
          <template #default="{ row }">
            <div class="app-icon">
              <img v-if="row.icon_type !== 'emoji' && row.icon" :src="row.icon" alt="" />
              <span v-else>{{ row.icon || '🧩' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="应用" min-width="200">
          <template #default="{ row }">
            <b>{{ row.name }}</b>
            <p class="desc">{{ row.description || '—' }}</p>
          </template>
        </el-table-column>
        <el-table-column label="分组" width="120">
          <template #default="{ row }">{{ catName(row.category_id) }}</template>
        </el-table-column>
        <el-table-column label="访问入口" min-width="200">
          <template #default="{ row }">
            <div class="urls">
              <el-tag
                v-for="u in row.urls"
                :key="u.id"
                size="small"
                class="url-tag"
                :type="u.access_type === 'domain' ? 'primary' : u.access_type === 'lan' ? 'success' : 'info'"
              >
                {{ ACCESS_LABEL[u.access_type as AccessType] }}·{{ u.label || u.url }}
              </el-tag>
              <span v-if="!row.urls.length" class="muted">未配置</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="打开方式" width="90">
          <template #default="{ row }">{{ OPEN_LABEL[row.open_mode as OpenMode] }}</template>
        </el-table-column>
        <el-table-column label="可见性" width="96">
          <template #default="{ row }">{{ VISIBILITY_LABEL[row.visibility as Visibility] }}</template>
        </el-table-column>
        <el-table-column v-if="isAdmin" label="启用" width="76">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" @change="toggleEnabled(row)" />
          </template>
        </el-table-column>
        <el-table-column v-if="isAdmin" label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="removeApp(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="还没有应用，点击右上角「新建应用」开始" />
        </template>
      </el-table>
    </section>

    <!-- 应用编辑抽屉 -->
    <el-drawer
      v-model="drawer"
      :title="draft.id ? '编辑应用' : '新建应用'"
      :size="isMobile ? '100%' : '620px'"
      destroy-on-close
    >
      <div class="drawer-body">
        <el-form label-position="top" size="large">
          <el-form-item label="名称" required>
            <el-input v-model="draft.name" placeholder="如：Jellyfin" maxlength="128" />
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="draft.description" placeholder="一句话描述（可选）" maxlength="512" />
          </el-form-item>
          <el-form-item label="分组">
            <el-select
              v-model="draft.category_id"
              placeholder="未分组"
              clearable
              style="width: 100%"
              @clear="draft.category_id = null"
            >
              <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </el-form-item>

          <el-form-item label="图标">
            <div class="icon-editor">
              <el-radio-group v-model="draft.icon_type">
                <el-radio-button value="url">URL</el-radio-button>
                <el-radio-button value="upload">上传</el-radio-button>
                <el-radio-button value="emoji">Emoji</el-radio-button>
              </el-radio-group>
              <div class="icon-preview">
                <img v-if="draft.icon_type !== 'emoji' && draft.icon" :src="draft.icon" alt="" />
                <span v-else>{{ draft.icon || '🧩' }}</span>
              </div>
              <template v-if="draft.icon_type === 'url'">
                <el-input v-model="draft.icon" placeholder="图标图片地址 https://…" />
                <div class="favicon-row">
                  <el-input v-model="faviconSource" placeholder="目标站地址，一键抓取其图标" />
                  <el-button @click="grabFavicon">抓取图标</el-button>
                </div>
              </template>
              <template v-else-if="draft.icon_type === 'upload'">
                <el-button @click="iconFileInput?.click()">选择图片（自动压方 ≤2MB）</el-button>
                <input ref="iconFileInput" type="file" accept="image/*" hidden @change="onIconFile" />
              </template>
              <template v-else>
                <el-input v-model="draft.icon" placeholder="直接输入 emoji，如 🎬" maxlength="8" />
                <div class="emoji-grid">
                  <button
                    v-for="e in EMOJIS"
                    :key="e"
                    type="button"
                    class="emoji"
                    @click="draft.icon = e"
                  >
                    {{ e }}
                  </button>
                </div>
              </template>
            </div>
          </el-form-item>

          <el-form-item label="访问入口（不同网络环境的地址）">
            <div class="url-editor">
              <div v-for="(row, i) in urlRows" :key="row.key" class="url-row">
                <el-select v-model="row.access_type" class="url-type">
                  <el-option label="域名" value="domain" />
                  <el-option label="内网" value="lan" />
                  <el-option label="SSH 隧道" value="ssh" />
                  <el-option label="VPN" value="vpn" />
                  <el-option label="自定义" value="custom" />
                </el-select>
                <el-input v-model="row.url" placeholder="地址，如 http://192.168.1.10:8096" />
                <el-input v-model="row.label" placeholder="标签" class="url-label" maxlength="64" />
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
              <el-button plain class="add-url" @click="addUrlRow">+ 添加入口</el-button>
            </div>
          </el-form-item>

          <div class="form-grid">
            <el-form-item label="打开方式">
              <el-select v-model="draft.open_mode" style="width: 100%">
                <el-option label="新标签页" value="newtab" />
                <el-option label="当前页" value="current" />
                <el-option label="iframe 内嵌" value="iframe" />
              </el-select>
            </el-form-item>
            <el-form-item label="可见性">
              <el-select v-model="draft.visibility" style="width: 100%">
                <el-option label="所有人" value="all" />
                <el-option label="仅管理员" value="admin" />
                <el-option label="指定用户" value="users" />
              </el-select>
            </el-form-item>
            <el-form-item label="探活方式（P6 生效）">
              <el-select v-model="draft.health_type" style="width: 100%">
                <el-option label="不探活" value="" />
                <el-option label="HTTP 状态码" value="http" />
                <el-option label="TCP 端口" value="tcp" />
                <el-option label="关键字" value="keyword" />
              </el-select>
            </el-form-item>
            <el-form-item label="探活目标">
              <el-input
                v-model="draft.health_target"
                placeholder="URL 或 host:port"
                :disabled="!draft.health_type"
              />
            </el-form-item>
          </div>

          <el-form-item label="标签（逗号分隔）">
            <el-input v-model="draft.tags" placeholder="如：媒体, 影音" />
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="draft.remark" type="textarea" :rows="2" placeholder="默认账号等提示信息" />
          </el-form-item>
          <el-form-item label="文档链接">
            <el-input v-model="draft.doc_url" placeholder="https://wiki.example.com/…" />
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="drawer = false">取消</el-button>
        <el-button type="primary" class="btn-gradient" :loading="saving" @click="saveApp">
          保存
        </el-button>
      </template>
    </el-drawer>

    <!-- 分组管理弹窗 -->
    <el-dialog v-model="catDialog" title="分组管理" :width="isMobile ? '94%' : '560px'">
      <div class="cat-list">
        <div v-for="c in categories" :key="c.id" class="cat-row">
          <span class="cat-icon">{{ c.icon || '📁' }}</span>
          <b>{{ c.name }}</b>
          <span class="muted">{{ c.app_count }} 个应用</span>
          <div class="cat-ops">
            <el-button link @click="moveCategory(c, -1)">↑</el-button>
            <el-button link @click="moveCategory(c, 1)">↓</el-button>
            <el-button link type="primary" @click="openCatEdit(c)">编辑</el-button>
            <el-button link type="danger" @click="removeCategory(c)">删除</el-button>
          </div>
        </div>
        <el-empty v-if="!categories.length" description="还没有分组，可先新建一个" :image-size="72" />
      </div>
      <el-divider />
      <div class="cat-form">
        <el-input v-model="catForm.icon" placeholder="图标 emoji" class="cat-icon-input" maxlength="4" />
        <el-input v-model="catForm.name" placeholder="分组名称" maxlength="64" />
        <el-button v-if="catForm.id" :loading="catSaving" type="primary" @click="saveCategory">
          保存修改
        </el-button>
        <el-button v-else :loading="catSaving" type="primary" class="btn-gradient" @click="saveCategory">
          新建分组
        </el-button>
        <el-button v-if="catForm.id" @click="openCatCreate">取消编辑</el-button>
      </div>
    </el-dialog>
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
  width: min(280px, 100%);
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
  background: rgba(91, 95, 241, 0.06);
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
.icon-preview {
  width: 56px;
  height: 56px;
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
.emoji-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.emoji {
  width: 34px;
  height: 34px;
  font-size: 18px;
  border: 1px solid var(--p-card-border);
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  transition: transform 0.12s, border-color 0.12s;
}
.emoji:hover {
  transform: scale(1.12);
  border-color: var(--p-primary);
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
.cat-icon-input {
  width: 96px;
  flex-shrink: 0;
}
</style>
