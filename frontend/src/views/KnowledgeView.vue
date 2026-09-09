<script setup lang="ts">
/**
 * 知识库（091）：数据源（服务器映射目录 / git 仓库）浏览与在线阅读编辑。
 *
 * - 左侧：数据源列表 + 懒加载目录树；
 * - 右侧：按文件类型分发查看器——markdown 渲染（marked+DOMPurify）/代码文本（可编辑，
 *   仅 local 源）/html iframe/图片/视频/音频/pdf 原文件流（Range 拖动）/office 服务端转 HTML；
 * - git 源只读，改动应回仓库后「同步」；local 源管理员可在线保存。
 */
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Delete as IconDelete,
  Refresh as IconRefresh,
  Setting as IconSetting,
} from '@element-plus/icons-vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import {
  knowledgeApi,
  type KnowledgeReadResult,
  type KnowledgeSource,
} from '../api/knowledge'
import { useAuthStore } from '../stores/auth'

const { t } = useI18n()
const auth = useAuthStore()

// ---------- 数据源 ----------
const sources = ref<KnowledgeSource[]>([])
const activeSource = ref<KnowledgeSource | null>(null)
const sourcesLoading = ref(false)
const treeRef = ref()
const treeKey = ref(0)

async function loadSources(keepSelection = false) {
  sourcesLoading.value = true
  try {
    sources.value = await knowledgeApi.sources()
    if (!keepSelection || !activeSource.value) {
      activeSource.value = sources.value[0] ?? null
      treeKey.value++
    } else {
      activeSource.value = sources.value.find((s) => s.id === activeSource.value?.id) ?? null
    }
  } finally {
    sourcesLoading.value = false
  }
}

function selectSource(src: KnowledgeSource) {
  activeSource.value = src
  currentPath.value = ''
  resetViewer()
  treeKey.value++ // 重建树
}

// ---------- 目录树（懒加载） ----------
type TreeNode = { name: string; path: string; type: 'dir' | 'file'; size: number | null; leaf: boolean }

async function loadNode(node: unknown, resolve: (items: TreeNode[]) => void) {
  const n = node as { level: number; data: TreeNode }
  if (!activeSource.value) return resolve([])
  const path = n.level === 0 ? '' : n.data.path
  try {
    const rows = await knowledgeApi.tree(activeSource.value.id, path)
    resolve(
      rows.map((r) => ({
        name: r.name,
        path: path ? `${path}/${r.name}` : r.name,
        type: r.type,
        size: r.size,
        leaf: r.type === 'file',
      })),
    )
  } catch {
    resolve([])
  }
}

function onNodeClick(data: TreeNode) {
  if (data.type === 'file') void openFile(data.path, data.size ?? undefined)
}

// ---------- 查看器 ----------
const currentPath = ref('')
const readResult = ref<KnowledgeReadResult | null>(null)
const readLoading = ref(false)
const editing = ref(false)
const editContent = ref('')
const saving = ref(false)
const viewSrc = ref('')
const officeRef = ref<HTMLDivElement>()
const officeHtml = ref('')
const officeError = ref('')

// 098 分片加载：超过阈值的大文本先加载首片，看多少传多少
const CHUNK_SIZE = 256 * 1024
const CHUNK_THRESHOLD = 512 * 1024

const renderedMd = computed(() => {
  if (!readResult.value?.text) return ''
  return DOMPurify.sanitize(marked.parse(readResult.value.text, { async: false }) as string)
})

function resetViewer() {
  readResult.value = null
  editing.value = false
  viewSrc.value = ''
  officeHtml.value = ''
  officeError.value = ''
}

/** Office 组件库渲染（092）：docx-preview / pptx-preview / SheetJS，按需懒加载 */
async function renderOffice(kind: 'docx' | 'pptx' | 'xlsx' | 'xls') {
  officeError.value = ''
  try {
    const buf = await fetch(viewSrc.value).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.arrayBuffer()
    })
    if (kind === 'docx') {
      await nextTick()
      const { renderAsync } = await import('docx-preview')
      if (!officeRef.value) return
      officeRef.value.innerHTML = ''
      await renderAsync(buf, officeRef.value, undefined, {
        inWrapper: true,
        ignoreLastRenderedPageBreak: true,
      })
    } else if (kind === 'pptx') {
      await nextTick()
      const { init } = await import('pptx-preview')
      if (!officeRef.value) return
      officeRef.value.innerHTML = ''
      const w = Math.max(720, officeRef.value.clientWidth || 900)
      init(officeRef.value, { width: w }).preview(buf)
    } else {
      const XLSX = await import('xlsx')
      const wb = XLSX.read(buf, { type: 'array' })
      const esc = (t: string) =>
        t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      officeHtml.value = wb.SheetNames.map(
        (n) => `<h3>${esc(n)}</h3>` + XLSX.utils.sheet_to_html(wb.Sheets[n]),
      ).join('')
    }
  } catch (e) {
    officeError.value = (e as Error).message
  }
}

/** zip 条目：经签名 URL 取 blob（预览开新页 / 下载） */
async function fetchEntryBlob(entry: { name: string }): Promise<Blob> {
  if (!activeSource.value) throw new Error('no source')
  const r = await knowledgeApi.rawSigned(activeSource.value.id, `${currentPath.value}!${entry.name}`)
  return fetch(r.url).then((x) => {
    if (!x.ok) throw new Error(`HTTP ${x.status}`)
    return x.blob()
  })
}

async function previewEntry(entry: { name: string }) {
  try {
    const blob = await fetchEntryBlob(entry)
    const url = URL.createObjectURL(blob)
    window.open(url, '_blank')
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function downloadEntry(entry: { name: string }) {
  try {
    const blob = await fetchEntryBlob(entry)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = entry.name.split('/').pop() || entry.name
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

function fmtSize(n: number | null): string {
  if (!n) return '-'
  if (n < 1024) return `${n} B`
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1048576).toFixed(1)} MB`
}

async function openFile(path: string, fileSize?: number) {
  if (!activeSource.value) return
  currentPath.value = path
  editing.value = false
  readLoading.value = true
  try {
    // 大文本文件分片：首片 256KB，避免整文件传输等待
    const chunked = (fileSize ?? 0) > CHUNK_THRESHOLD
    readResult.value = await knowledgeApi.read(
      activeSource.value.id,
      path,
      chunked ? { offset: 0, chunk: CHUNK_SIZE } : undefined,
    )
    // iframe/img/video 无法携带请求头：换短期签名 URL（092）
    const kind = readResult.value?.kind ?? ''
    if (['html', 'image', 'video', 'audio', 'pdf', 'binary', 'docx', 'pptx', 'xlsx', 'xls'].includes(kind)) {
      const r = await knowledgeApi.rawSigned(activeSource.value.id, path)
      viewSrc.value = r.url
    }
    // doc/ppt 老格式：经 LibreOffice 转 PDF 预览（签名 URL）
    if (kind === 'legacy') {
      if (readResult.value?.converter === false) {
        viewSrc.value = ''
      } else {
        const r = await knowledgeApi.officePdfSigned(activeSource.value.id, path)
        viewSrc.value = r.url
      }
    }
    // Office 组件库渲染：容器就绪后异步加载对应库
    if (['docx', 'pptx', 'xlsx', 'xls'].includes(kind)) {
      void nextTick().then(() => renderOffice(kind as 'docx' | 'pptx' | 'xlsx' | 'xls'))
    }
  } catch (e) {
    ElMessage.error((e as Error).message)
    resetViewer()
  } finally {
    readLoading.value = false
  }
}

function startEdit() {
  if (!readResult.value?.text) return
  editContent.value = readResult.value.text
  editing.value = true
}

/** 续传一片（追加文本）；loadAll=循环拉取直到完整（供编辑前调用） */
async function loadMore(loadAll = false) {
  if (!activeSource.value || !readResult.value?.has_more) return
  const id = activeSource.value.id
  const path = currentPath.value
  do {
    const offset = (readResult.value.size ?? 0) - (readResult.value.text?.length ?? 0)
    const r = await knowledgeApi.read(id, path, { offset, chunk: 1024 * 1024 })
    if (readResult.value.text === undefined) readResult.value.text = ''
    readResult.value.text += r.text ?? ''
    readResult.value.has_more = r.has_more
    readResult.value.size = r.size ?? readResult.value.size
  } while (loadAll && readResult.value.has_more)
}

async function startEditLoadAll() {
  if (readResult.value?.has_more) {
    readLoading.value = true
    try {
      await loadMore(true)
    } finally {
      readLoading.value = false
    }
  }
  startEdit()
}

async function saveEdit() {
  if (!activeSource.value || !currentPath.value) return
  saving.value = true
  try {
    await knowledgeApi.write(activeSource.value.id, currentPath.value, editContent.value)
    ElMessage.success(t('knowledge.saved'))
    editing.value = false
    readResult.value = await knowledgeApi.read(activeSource.value.id, currentPath.value)
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    saving.value = false
  }
}


// ---------- 源管理（管理员） ----------
const srcDialog = ref(false)
const srcSaving = ref(false)
const srcSyncing = ref(false)
const srcForm = reactive({
  id: null as number | null,
  name: '',
  kind: 'local' as 'local' | 'git',
  path: '',
  branch: '',
  username: '',
  password: '',
  enabled: true,
})

function openSourceCreate() {
  Object.assign(srcForm, { id: null, name: '', kind: 'local', path: '', branch: '', username: '', password: '', enabled: true })
  srcDialog.value = true
}

function openSourceEdit(src: KnowledgeSource) {
  Object.assign(srcForm, {
    id: src.id, name: src.name, kind: src.kind,
    path: src.kind === 'local' ? src.path : src.url,
    branch: src.branch, username: '', password: '', enabled: src.enabled,
  })
  srcDialog.value = true
}

async function saveSource() {
  srcSaving.value = true
  try {
    const payload: Record<string, unknown> = {
      name: srcForm.name, kind: srcForm.kind, path: srcForm.path,
      branch: srcForm.branch, username: srcForm.username, enabled: srcForm.enabled,
    }
    if (srcForm.password) payload.password = srcForm.password
    if (srcForm.id) await knowledgeApi.updateSource(srcForm.id, payload)
    else await knowledgeApi.createSource(payload as never)
    ElMessage.success(t('knowledge.sourceSaved'))
    srcDialog.value = false
    await loadSources()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    srcSaving.value = false
  }
}

async function syncSource(src: KnowledgeSource) {
  srcSyncing.value = true
  try {
    const r = await knowledgeApi.syncSource(src.id)
    ElMessage.success(t('knowledge.syncOk', { commit: r.commit.slice(0, 8) }))
    await loadSources(true)
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    srcSyncing.value = false
  }
}

// ---------- 目录选择框（091 增补）：映射目录逐级下钻，替代手动输入 ----------
const dirPicker = ref(false)
const pickerLoading = ref(false)
const pickerPath = ref('')
const pickerRoots = ref<Array<{ path: string; label: string }>>([])
const pickerDirs = ref<string[]>([])
const pickerParent = ref<string | null>(null)
const pickerExists = ref<boolean | null>(null)

async function loadPicker(path: string) {
  pickerLoading.value = true
  try {
    const r = await knowledgeApi.localDirs(path)
    pickerPath.value = r.path
    pickerRoots.value = r.roots ?? []
    pickerDirs.value = r.dirs ?? []
    pickerParent.value = r.parent
    pickerExists.value = r.exists ?? null
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    pickerLoading.value = false
  }
}

function openPicker() {
  dirPicker.value = true
  void loadPicker(srcForm.path)
}

function choosePicker() {
  srcForm.path = pickerPath.value
  dirPicker.value = false
}

async function removeSource(src: KnowledgeSource) {
  const ok = await ElMessageBox.confirm(
    t('knowledge.removeConfirm', { name: src.name }),
    t('common.confirm'),
    { type: 'warning' },
  ).then(() => true, () => false)
  if (!ok) return
  try {
    await knowledgeApi.removeSource(src.id)
    await loadSources()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

onMounted(() => loadSources())
</script>

<template>
  <div class="kb">
    <!-- 左：数据源 + 目录树 -->
    <aside class="kb-side glass">
      <div class="side-head">
        <h3>{{ t('knowledge.title') }}</h3>
        <el-button v-if="auth.isAdmin" size="small" :icon="IconSetting" circle @click="openSourceCreate" />
      </div>
      <div class="src-list">
        <div
          v-for="s in sources"
          :key="s.id"
          class="src-item"
          :class="{ active: activeSource?.id === s.id }"
          @click="selectSource(s)"
        >
          <span class="src-name">{{ s.name }}</span>
          <el-tag size="small" :type="s.kind === 'git' ? 'warning' : 'info'" effect="plain">{{ s.kind }}</el-tag>
          <span v-if="s.last_status === 'failed'" class="src-err" :title="s.last_error">!</span>
          <span class="spacer" />
          <template v-if="auth.isAdmin">
            <el-button
              v-if="s.kind === 'git'"
              size="small"
              :icon="IconRefresh"
              circle
              link
              :loading="srcSyncing"
              @click.stop="syncSource(s)"
            />
            <el-button size="small" :icon="IconSetting" circle link @click.stop="openSourceEdit(s)" />
            <el-button size="small" :icon="IconDelete" circle link type="danger" @click.stop="removeSource(s)" />
          </template>
        </div>
        <p v-if="!sources.length && !sourcesLoading" class="kb-empty">{{ t('knowledge.noSources') }}</p>
      </div>

      <div v-if="activeSource" class="tree-wrap">
        <el-tree
          ref="treeRef"
          :key="treeKey"
          lazy
          :load="loadNode"
          :props="{ label: 'name', isLeaf: 'leaf' }"
          node-key="path"
          highlight-current
          @node-click="onNodeClick"
        />
      </div>
      <p v-else class="kb-hint">{{ t('knowledge.pickSource') }}</p>
    </aside>

    <!-- 右：查看器 -->
    <section class="kb-view glass" v-loading="readLoading">
      <template v-if="readResult">
        <header class="view-head">
          <span class="view-path">{{ currentPath }}</span>
          <span class="spacer" />
          <a v-if="['image', 'video', 'audio', 'pdf', 'binary', 'html'].includes(readResult.kind)" :href="viewSrc" target="_blank" class="dl-link">{{ t('knowledge.openRaw') }}</a>
          <el-button
            v-if="readResult.editable && !editing"
            size="small"
            type="primary"
            :disabled="readResult.has_more"
            :title="readResult.has_more ? t('knowledge.editNeedFull') : ''"
            @click="startEditLoadAll"
          >
            {{ t('common.edit') }}
          </el-button>
          <template v-if="editing">
            <el-button size="small" type="primary" class="btn-gradient" :loading="saving" @click="saveEdit">
              {{ t('common.save') }}
            </el-button>
            <el-button size="small" @click="editing = false">{{ t('common.cancel') }}</el-button>
          </template>
        </header>

        <div class="view-body">
          <!-- 大文件分片加载进度（098） -->
          <div v-if="readResult.has_more" class="chunk-banner">
            <span>
              {{ t('knowledge.chunkLoaded', {
                loaded: fmtSize(readResult.text?.length ?? 0),
                total: fmtSize(readResult.size ?? 0),
              }) }}
            </span>
            <el-button size="small" :loading="readLoading" @click="loadMore(false)">
              {{ t('knowledge.chunkMore') }}
            </el-button>
            <el-button size="small" :loading="readLoading" @click="startEditLoadAll">
              {{ t('knowledge.chunkAll') }}
            </el-button>
          </div>
          <div class="view-body">
          <!-- markdown：渲染或编辑 -->
          <template v-if="readResult.kind === 'markdown'">
            <textarea v-if="editing" v-model="editContent" class="kb-editor" spellcheck="false" />
            <div v-else class="kb-md" v-html="renderedMd" />
          </template>

          <!-- 文本/代码：查看或编辑 -->
          <template v-else-if="['text', 'code'].includes(readResult.kind)">
            <textarea v-if="editing" v-model="editContent" class="kb-editor" spellcheck="false" />
            <pre v-else class="kb-code">{{ readResult.text }}</pre>
          </template>

          <!-- html：沙箱 iframe -->
          <iframe
            v-else-if="readResult.kind === 'html'"
            :src="viewSrc"
            class="kb-frame"
            sandbox="allow-same-origin"
          />

          <!-- pdf：原生预览 -->
          <iframe v-else-if="readResult.kind === 'pdf'" :src="viewSrc" class="kb-frame" />

          <!-- 图片 -->
          <div v-else-if="readResult.kind === 'image'" class="kb-center">
            <img :src="viewSrc" class="kb-img" :alt="currentPath" />
          </div>

          <!-- 视频/音频 -->
          <div v-else-if="['video', 'audio'].includes(readResult.kind)" class="kb-center">
            <video v-if="readResult.kind === 'video'" :src="viewSrc" controls class="kb-media" />
            <audio v-else :src="viewSrc" controls />
          </div>

          <!-- office：组件库渲染（docx-preview / pptx-preview / SheetJS） -->
          <template v-else-if="['docx', 'pptx', 'xlsx', 'xls'].includes(readResult.kind)">
            <el-alert
              v-if="officeError"
              :title="t('knowledge.officeFail', { msg: officeError })"
              type="warning"
              :closable="false"
            />
            <div v-show="readResult.kind === 'xlsx' || readResult.kind === 'xls'" class="kb-md" v-html="officeHtml" />
            <div v-show="readResult.kind === 'docx' || readResult.kind === 'pptx'" ref="officeRef" class="kb-office" />
          </template>

          <!-- doc/ppt 老格式：LibreOffice 转 PDF 预览（097） -->
          <template v-else-if="readResult.kind === 'legacy'">
            <div v-if="readResult.converter === false" class="kb-center kb-binary">
              <p>{{ t('knowledge.legacyNoConverter') }}</p>
              <a :href="viewSrc" target="_blank"><el-button size="small" type="primary">{{ t('knowledge.download') }}</el-button></a>
            </div>
            <iframe v-else :src="viewSrc" class="kb-frame" />
          </template>

          <!-- zip：条目清单 + 单文件提取 -->
          <template v-else-if="readResult.kind === 'zip'">
            <el-table :data="readResult.entries" size="small" max-height="520">
              <el-table-column :label="t('knowledge.zipName')" min-width="260">
                <template #default="{ row }">
                  <span class="path-cell">{{ row.name }}</span>
                </template>
              </el-table-column>
              <el-table-column :label="t('knowledge.zipSize')" width="110" align="right">
                <template #default="{ row }">{{ fmtSize(row.size) }}</template>
              </el-table-column>
              <el-table-column :label="t('knowledge.zipPacked')" width="110" align="right">
                <template #default="{ row }">{{ fmtSize(row.compress_size) }}</template>
              </el-table-column>
              <el-table-column :label="t('ports.colOp')" width="140">
                <template #default="{ row }">
                  <el-button size="small" link type="primary" @click="previewEntry(row)">{{ t('knowledge.zipPreview') }}</el-button>
                  <el-button size="small" link @click="downloadEntry(row)">{{ t('knowledge.download') }}</el-button>
                </template>
              </el-table-column>
            </el-table>
          </template>

          <!-- 其它：下载 -->
          <div v-else class="kb-center kb-binary">
            <p>{{ t('knowledge.binaryHint') }}</p>
            <a :href="viewSrc" target="_blank"><el-button size="small" type="primary">{{ t('knowledge.download') }}</el-button></a>
          </div>
        </div>
      </div>
      </template>
      <div v-else class="kb-center kb-placeholder">
        <p>{{ t('knowledge.pickFile') }}</p>
      </div>
    </section>

    <!-- 源管理弹窗 -->
    <el-dialog append-to-body v-model="srcDialog" :title="srcForm.id ? t('knowledge.editSource') : t('knowledge.addSource')" width="520px">
      <el-form label-position="top">
        <el-form-item :label="t('knowledge.srcName')">
          <el-input v-model="srcForm.name" maxlength="64" />
        </el-form-item>
        <el-form-item :label="t('knowledge.srcKind')">
          <el-radio-group v-model="srcForm.kind" :disabled="!!srcForm.id">
            <el-radio-button value="local">{{ t('knowledge.kindLocal') }}</el-radio-button>
            <el-radio-button value="git">{{ t('knowledge.kindGit') }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="srcForm.kind === 'local'" :label="t('knowledge.srcPath')">
          <div class="path-pick">
            <el-input v-model="srcForm.path" :placeholder="t('knowledge.srcPickPh')" readonly />
            <el-button type="primary" plain @click="openPicker">{{ t('knowledge.pickBtn') }}</el-button>
          </div>
          <div class="form-hint">{{ t('knowledge.srcPathHint') }}</div>
        </el-form-item>
        <template v-else>
          <el-form-item :label="t('knowledge.srcUrl')">
            <el-input v-model="srcForm.path" placeholder="https://gitee.com/user/repo.git" />
          </el-form-item>
          <el-form-item :label="t('knowledge.srcBranch')">
            <el-input v-model="srcForm.branch" :placeholder="t('knowledge.srcBranchPh')" />
          </el-form-item>
          <el-form-item :label="t('knowledge.srcUser')">
            <el-input v-model="srcForm.username" autocomplete="off" />
          </el-form-item>
          <el-form-item :label="t('knowledge.srcPass')">
            <el-input v-model="srcForm.password" type="password" show-password :placeholder="t('knowledge.srcPassPh')" autocomplete="new-password" />
            <div class="form-hint">{{ t('knowledge.srcPassHint') }}</div>
          </el-form-item>
        </template>
        <el-form-item :label="t('knowledge.srcEnabled')">
          <el-switch v-model="srcForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="srcDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" class="btn-gradient" :loading="srcSaving" @click="saveSource">
          {{ t('common.save') }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 目录选择框（091 增补）：逐级下钻 -->
    <el-dialog append-to-body v-model="dirPicker" :title="t('knowledge.pickTitle')" width="480px">
      <div v-loading="pickerLoading" class="dir-pick">
        <div class="dp-crumb">
          <span class="dp-label">{{ t('knowledge.pickCurrent') }}</span>
          <span class="dp-path">{{ pickerPath || t('knowledge.pickStart') }}</span>
        </div>

        <template v-if="pickerExists === null">
          <p class="dp-hint">{{ t('knowledge.pickRootsHint') }}</p>
          <div
            v-for="r in pickerRoots"
            :key="r.path"
            class="dp-row"
            @click="loadPicker(r.path)"
          >
            <span class="dp-name">{{ r.label }}</span>
            <span class="dp-sub">{{ r.path }}</span>
          </div>
          <div class="dp-row" @click="loadPicker('/')">
            <span class="dp-name">{{ t('knowledge.pickFromRoot') }}</span>
          </div>
        </template>

        <template v-else>
          <div v-if="pickerParent" class="dp-row" @click="loadPicker(pickerParent)">
            <span class="dp-up">⬆️ {{ t('knowledge.pickUp') }}</span>
          </div>
          <div v-for="d in pickerDirs" :key="d" class="dp-row" @click="loadPicker(d)">
            <span class="dp-name">📁 {{ d.split('/').pop() }}</span>
            <span class="spacer" />
          </div>
          <p v-if="!pickerDirs.length" class="dp-hint">{{ t('knowledge.pickNoSub') }}</p>
          <div class="dp-foot">
            <el-button size="small" @click="loadPicker('')">{{ t('knowledge.pickRestart') }}</el-button>
            <el-button size="small" type="primary" class="btn-gradient" :disabled="pickerExists !== true" @click="choosePicker">
              {{ t('knowledge.pickChoose') }}
            </el-button>
          </div>
        </template>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.kb-md :deep(h1) { font-size: 26px; margin: 18px 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--p-card-border); }
.kb-md :deep(h2) { font-size: 21px; margin: 16px 0 10px; padding-bottom: 6px; border-bottom: 1px solid var(--p-card-border); }
.kb-md :deep(h3) { font-size: 17px; margin: 14px 0 8px; }
.kb-md :deep(h4), .kb-md :deep(h5), .kb-md :deep(h6) { font-size: 14.5px; margin: 12px 0 6px; }
.kb-md :deep(p) { margin: 8px 0; }
.kb-md :deep(a) { color: var(--p-primary); }
.kb-md :deep(ul), .kb-md :deep(ol) { padding-left: 24px; margin: 8px 0; }
.kb-md :deep(li) { margin: 3px 0; }
.kb-md :deep(blockquote) {
  margin: 10px 0;
  padding: 6px 14px;
  border-left: 4px solid color-mix(in srgb, var(--p-primary) 55%, transparent);
  background: var(--p-soft);
  color: var(--p-muted);
  border-radius: 0 var(--p-radius-sm) var(--p-radius-sm) 0;
}
.kb-md :deep(code) {
  font-family: ui-monospace, monospace;
  font-size: 12.5px;
  background: var(--p-soft);
  border-radius: 4px;
  padding: 2px 6px;
}
.kb-md :deep(pre) {
  background: var(--p-soft);
  border: 1px solid var(--p-card-border);
  border-radius: var(--p-radius-sm);
  padding: 12px 14px;
  overflow: auto;
  margin: 10px 0;
}
.kb-md :deep(pre code) {
  background: transparent;
  padding: 0;
  font-size: 12.5px;
  line-height: 1.6;
}
.kb-md :deep(table) {
  border-collapse: collapse;
  margin: 12px 0;
  width: 100%;
  font-size: 13px;
}
.kb-md :deep(th),
.kb-md :deep(td) {
  border: 1px solid var(--p-card-border);
  padding: 6px 12px;
  text-align: left;
}
.kb-md :deep(th) {
  background: var(--p-soft);
  font-weight: 700;
}
.kb-md :deep(tr:nth-child(2n)) {
  background: color-mix(in srgb, var(--p-soft) 55%, transparent);
}
.kb-md :deep(img) {
  max-width: 100%;
  border-radius: var(--p-radius-sm);
}
.kb-md :deep(hr) {
  border: none;
  border-top: 1px solid var(--p-card-border);
  margin: 16px 0;
}
.path-pick {
  display: flex;
  gap: 8px;
  width: 100%;
}
.dir-pick {
  min-height: 200px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.dp-crumb {
  display: flex;
  gap: 8px;
  align-items: baseline;
  padding: 4px 8px;
  background: var(--p-soft);
  border-radius: var(--p-radius-sm);
}
.dp-label {
  color: var(--p-muted);
  font-size: 12px;
  flex-shrink: 0;
}
.dp-path {
  font-family: ui-monospace, monospace;
  font-size: 12px;
  word-break: break-all;
}
.dp-hint {
  color: var(--p-muted);
  font-size: 12.5px;
  margin: 6px 0;
}
.dp-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: var(--p-radius-sm);
  cursor: pointer;
  font-size: 13px;
}
.dp-row:hover {
  background: var(--p-soft);
}
.dp-name {
  font-weight: 500;
}
.dp-sub {
  color: var(--p-muted);
  font-size: 11.5px;
  font-family: ui-monospace, monospace;
}
.dp-up {
  color: var(--p-muted);
}
.dp-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}
.kb {
  height: 100%;
  display: flex;
  gap: 14px;
  min-height: 0;
}
.kb-side {
  width: clamp(240px, 22vw, 320px);
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  padding: 12px 14px;
  min-height: 0;
}
.side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.side-head h3 {
  margin: 0;
  font-size: 14px;
}
.src-list {
  flex: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 8px;
}
.src-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-radius: var(--p-radius-sm);
  cursor: pointer;
}
.src-item:hover {
  background: var(--p-soft);
}
.src-item.active {
  background: color-mix(in srgb, var(--p-primary) 14%, transparent);
}
.src-name {
  font-weight: 600;
  font-size: 13px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.src-err {
  color: var(--el-color-danger);
  font-weight: 700;
}
.spacer {
  flex: 1;
}
.tree-wrap {
  flex: 1;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  border-top: 1px solid var(--p-card-border);
  padding-top: 8px;
}
.kb-empty,
.kb-hint {
  color: var(--p-muted);
  font-size: 12.5px;
}
.kb-view {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  padding: 12px 16px;
}
.view-head {
  flex: none;
  display: flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--p-card-border);
  margin-bottom: 10px;
}
.view-path {
  font-family: ui-monospace, monospace;
  font-size: 12.5px;
  color: var(--p-muted);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dl-link {
  font-size: 12.5px;
  color: var(--p-primary);
}
.chunk-banner {
  flex: none;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 12px;
  margin-bottom: 8px;
  border-radius: var(--p-radius-sm);
  background: color-mix(in srgb, var(--p-primary) 10%, transparent);
  font-size: 12.5px;
}
.view-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.view-body .view-body {
  flex: 1;
}
.kb-md {
  overflow: auto;
  line-height: 1.7;
  font-size: 14px;
}
.kb-code {
  overflow: auto;
  font-family: ui-monospace, monospace;
  font-size: 12.5px;
  line-height: 1.6;
  margin: 0;
  white-space: pre;
}
.kb-editor {
  flex: 1;
  min-height: 0;
  resize: none;
  border: 1px solid var(--p-card-border);
  border-radius: var(--p-radius-sm);
  background: var(--p-soft);
  color: var(--p-text);
  font-family: ui-monospace, monospace;
  font-size: 13px;
  line-height: 1.6;
  padding: 10px 12px;
}
.kb-editor:focus {
  outline: 2px solid color-mix(in srgb, var(--p-primary) 40%, transparent);
}
.kb-office {
  flex: 1;
  min-height: 0;
  overflow: auto;
  background: #fff;
  border-radius: var(--p-radius-sm);
}
.kb-office :deep(table) {
  max-width: 100%;
}
.kb-frame {
  flex: 1;
  width: 100%;
  border: none;
  background: #fff;
  border-radius: var(--p-radius-sm);
}
.kb-center {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  overflow: auto;
}
.kb-img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}
.kb-media {
  max-width: 100%;
  width: min(720px, 100%);
}
.kb-placeholder {
  color: var(--p-muted);
  font-size: 13px;
}
.kb-binary {
  color: var(--p-muted);
  font-size: 13px;
}
.form-hint {
  width: 100%;
  font-size: 12px;
  color: var(--p-muted);
}
</style>
