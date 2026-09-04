<script setup lang="ts">
/**
 * 文件管理面板（M11-1~4/6；dev-plan P16.2）。
 *
 * - 白名单目录浏览（面包屑导航）；管理员可上传/建目录/重命名/移动/删除；
 * - 下载经 base64 JSON（密文）；媒体预览走短时签名直链（图片/视频原生播放）；
 * - 未配置白名单时显示空态引导到设置。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowLeft as IconBack,
  Delete as IconDelete,
  Download as IconDownload,
  FolderAdd as IconMkdir,
  Plus as IconPlus,
  Refresh as IconRefresh,
  View as IconView,
} from '@element-plus/icons-vue'
import type { Component } from 'vue'
import { filesApi } from '../api/files'
import type { FileEntry, FileRoot } from '../api/files'
import { useAuthStore } from '../stores/auth'
import { formatBytes } from '../utils/format'
import { ELEMENT_ICON_MAP } from '../utils/elementIcons'

const { t } = useI18n()
const auth = useAuthStore()

const roots = ref<FileRoot[]>([])
const activeRoot = ref('')
const path = ref('')
const entries = ref<FileEntry[]>([])
const loading = ref(false)

const crumbs = computed(() => {
  const parts = path.value ? path.value.split('/') : []
  const out = [{ name: roots.value.find((r) => r.name === activeRoot.value)?.name ?? activeRoot.value, p: '' }]
  let acc = ''
  for (const part of parts) {
    acc = acc ? `${acc}/${part}` : part
    out.push({ name: part, p: acc })
  }
  return out
})

const IMAGE_RE = /\.(png|jpe?g|gif|webp|bmp|svg)$/i
const VIDEO_RE = /\.(mp4|webm|mov|m4v)$/i
const AUDIO_RE = /\.(mp3|wav|ogg|m4a|flac)$/i

async function loadRoots() {
  try {
    roots.value = await filesApi.roots()
    if (roots.value.length && !activeRoot.value) {
      activeRoot.value = roots.value[0]!.name
      await load()
    }
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function load() {
  if (!activeRoot.value) return
  loading.value = true
  try {
    entries.value = (await filesApi.list(activeRoot.value, path.value)).entries
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

function enter(e: FileEntry) {
  if (!e.dir) return
  path.value = path.value ? `${path.value}/${e.name}` : e.name
  load()
}

function crumbTo(p: string) {
  path.value = p
  load()
}

function fmtSize(n: number): string {
  return n < 1024 ? `${n} B` : formatBytes(n)
}

// ---- 操作 ----
const fileInput = ref<HTMLInputElement | null>(null)

function pickUpload() {
  fileInput.value?.click()
}

async function onUpload(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (file.size > 70 * 1024 * 1024) {
    ElMessage.warning(t('eff.fileTooLarge'))
    return
  }
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = () => reject(new Error(t('eff.readFail')))
    reader.readAsDataURL(file)
  })
  try {
    await filesApi.upload(activeRoot.value, path.value, file.name, dataUrl.split(',')[1] ?? '')
    ElMessage.success(t('common.save'))
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function mkdir() {
  try {
    const { value } = await ElMessageBox.prompt(t('eff.dirName'), t('eff.mkdir'), {
      inputPattern: /\S+/,
      inputErrorMessage: t('eff.nameRequired'),
    })
    await filesApi.mkdir(activeRoot.value, path.value, value.trim())
    await load()
  } catch {
    /* 取消 */
  }
}

async function rename(e: FileEntry) {
  try {
    const { value } = await ElMessageBox.prompt(t('eff.newName'), t('eff.rename'), {
      inputValue: e.name,
      inputPattern: /\S+/,
      inputErrorMessage: t('eff.nameRequired'),
    })
    await filesApi.rename(activeRoot.value, joinPath(e.name), value.trim())
    await load()
  } catch {
    /* 取消 */
  }
}

async function moveTo(e: FileEntry) {
  try {
    const { value } = await ElMessageBox.prompt(t('eff.destDir'), t('eff.move'), {
      inputValue: path.value,
    })
    await filesApi.move(activeRoot.value, joinPath(e.name), value.trim())
    await load()
  } catch {
    /* 取消 */
  }
}

async function remove(e: FileEntry) {
  try {
    await ElMessageBox.confirm(t('eff.deleteConfirm', { name: e.name }), t('common.confirm'), { type: 'warning' })
  } catch {
    return
  }
  try {
    await filesApi.remove(activeRoot.value, joinPath(e.name))
    await load()
  } catch (err) {
    ElMessage.error((err as Error).message)
  }
}

function joinPath(name: string): string {
  return path.value ? `${path.value}/${name}` : name
}

async function download(e: FileEntry) {
  try {
    const r = await filesApi.download(activeRoot.value, joinPath(e.name))
    const blob = new Blob([new Uint8Array([...atob(r.data)].map((c) => c.charCodeAt(0)))])
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = r.filename
    a.click()
    URL.revokeObjectURL(a.href)
  } catch (err) {
    ElMessage.error((err as Error).message)
  }
}

// ---- 预览 ----
const preview = ref<{ visible: boolean; url: string; name: string; kind: 'image' | 'video' | 'audio' }>({
  visible: false,
  url: '',
  name: '',
  kind: 'image',
})

async function openPreview(e: FileEntry) {
  const kind = IMAGE_RE.test(e.name) ? 'image' : VIDEO_RE.test(e.name) ? 'video' : AUDIO_RE.test(e.name) ? 'audio' : null
  if (!kind) {
    ElMessage.warning(t('eff.noPreview'))
    return
  }
  try {
    const r = await filesApi.rawUrl(activeRoot.value, joinPath(e.name))
    preview.value = { visible: true, url: r.url, name: e.name, kind }
  } catch (err) {
    ElMessage.error((err as Error).message)
  }
}

function kindOf(name: string): 'dir' | 'image' | 'video' | 'audio' | 'file' {
  if (IMAGE_RE.test(name)) return 'image'
  if (VIDEO_RE.test(name)) return 'video'
  if (AUDIO_RE.test(name)) return 'audio'
  return 'file'
}

const KIND_ICON = {
  dir: 'Folder',
  image: 'Picture',
  video: 'VideoPlay',
  audio: 'Headset',
  file: 'Document',
} as const

function iconFor(e: FileEntry): Component {
  return ELEMENT_ICON_MAP[KIND_ICON[kindOf(e.name)]] ?? ELEMENT_ICON_MAP.Document
}

onMounted(loadRoots)
</script>

<template>
  <div class="files">
    <template v-if="roots.length">
      <header class="files-bar glass">
        <el-select
          v-if="roots.length > 1"
          v-model="activeRoot"
          size="small"
          style="width: 160px"
          @change="path = ''; load()"
        >
          <el-option v-for="r in roots" :key="r.name" :value="r.name" :label="r.name" />
        </el-select>
        <el-breadcrumb separator="/">
          <el-breadcrumb-item v-for="c in crumbs" :key="c.p">
            <a class="crumb" @click.prevent="crumbTo(c.p)">{{ c.name }}</a>
          </el-breadcrumb-item>
        </el-breadcrumb>
        <span class="spacer" />
        <template v-if="auth.isAdmin">
          <el-button size="small" :icon="IconPlus" @click="pickUpload">{{ t('eff.upload') }}</el-button>
          <el-button size="small" :icon="IconMkdir" @click="mkdir">{{ t('eff.mkdir') }}</el-button>
        </template>
        <el-button size="small" :icon="IconRefresh" circle @click="load" />
        <input ref="fileInput" type="file" class="hidden-input" @change="onUpload" />
      </header>

      <section class="files-body glass" v-loading="loading">
        <table class="file-table">
          <thead>
            <tr>
              <th>{{ t('eff.colName') }}</th>
              <th class="w-size">{{ t('eff.colSize') }}</th>
              <th class="w-time">{{ t('eff.colMtime') }}</th>
              <th class="w-ops" />
            </tr>
          </thead>
          <tbody>
            <tr v-for="e in entries" :key="e.name" class="file-row" :class="{ dir: e.dir }" @dblclick="e.dir ? enter(e) : openPreview(e)">
              <td class="name-cell" @click="e.dir ? enter(e) : openPreview(e)">
                <el-icon :size="15" class="file-icon">
                  <component :is="iconFor(e)" />
                </el-icon>
                <span class="file-name">{{ e.name }}</span>
              </td>
              <td class="w-size">{{ e.dir ? '—' : fmtSize(e.size) }}</td>
              <td class="w-time">{{ e.mtime.replace('T', ' ') }}</td>
              <td class="w-ops">
                <el-button v-if="!e.dir" link size="small" :icon="IconView" :title="t('eff.preview')" @click="openPreview(e)" />
                <el-button v-if="!e.dir" link size="small" :icon="IconDownload" :title="t('eff.download')" @click="download(e)" />
                <template v-if="auth.isAdmin">
                  <el-button link size="small" :title="t('eff.rename')" @click="rename(e)">{{ t('eff.renameShort') }}</el-button>
                  <el-button link size="small" :title="t('eff.move')" @click="moveTo(e)">→</el-button>
                  <el-button link size="small" :icon="IconDelete" class="danger-btn" :title="t('common.delete')" @click="remove(e)" />
                </template>
              </td>
            </tr>
            <tr v-if="!entries.length && !loading">
              <td colspan="4" class="empty-cell">{{ t('common.noData') }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>

    <section v-else class="glass empty-state">
      <el-icon :size="34"><IconBack /></el-icon>
      <p>{{ t('eff.noRoots') }}</p>
      <el-button v-if="auth.isAdmin" type="primary" class="btn-gradient" @click="$router.push('/settings')">
        {{ t('eff.goSettings') }}
      </el-button>
    </section>

    <el-dialog v-model="preview.visible" :title="preview.name" width="640px" append-to-body class="preview-dlg">
      <div class="preview-body">
        <img v-if="preview.kind === 'image'" :src="preview.url" :alt="preview.name" />
        <video v-else-if="preview.kind === 'video'" :src="preview.url" controls autoplay />
        <audio v-else :src="preview.url" controls />
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.files {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.files-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
}
.crumb {
  cursor: pointer;
  color: var(--p-primary);
}
.spacer {
  flex: 1;
}
.hidden-input {
  display: none;
}
.files-body {
  padding: 6px 10px;
  min-height: 200px;
}
.file-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.file-table th {
  text-align: left;
  font-weight: 500;
  color: var(--p-muted);
  padding: 8px 10px;
  border-bottom: 1px solid var(--p-card-border);
}
.file-table td {
  padding: 7px 10px;
  border-bottom: 1px solid color-mix(in srgb, var(--p-card-border) 50%, transparent);
}
.file-row:hover td {
  background: color-mix(in srgb, var(--p-primary) 5%, transparent);
}
.name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.file-row.dir .file-name {
  font-weight: 600;
}
.file-icon {
  color: var(--p-primary);
  flex-shrink: 0;
}
.file-name {
  word-break: break-all;
}
.w-size {
  width: 90px;
}
.w-time {
  width: 150px;
}
.w-ops {
  width: 210px;
  text-align: right;
  white-space: nowrap;
}
.danger-btn {
  color: var(--el-color-danger);
}
.empty-cell {
  text-align: center;
  color: var(--p-muted);
  padding: 26px 0 !important;
}
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 46px 0;
  color: var(--p-muted);
}
.preview-body img,
.preview-body video {
  max-width: 100%;
  max-height: 64vh;
  border-radius: 8px;
  display: block;
  margin: 0 auto;
}
.preview-body audio {
  width: 100%;
}
</style>
