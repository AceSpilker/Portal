<script setup lang="ts">
/**
 * 知识库（091）：数据源（服务器映射目录 / git 仓库）浏览与在线阅读编辑。
 *
 * - 左侧：数据源列表 + 懒加载目录树；
 * - 右侧：按文件类型分发查看器——markdown 渲染（marked+DOMPurify）/代码文本（可编辑，
 *   仅 local 源）/html iframe/图片/视频/音频/pdf 原文件流（Range 拖动）/office 服务端转 HTML；
 * - git 源只读，改动应回仓库后「同步」；local 源管理员可在线保存。
 */
import { computed, onMounted, reactive, ref } from 'vue'
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
  if (data.type === 'file') void openFile(data.path)
}

// ---------- 查看器 ----------
const currentPath = ref('')
const readResult = ref<KnowledgeReadResult | null>(null)
const readLoading = ref(false)
const editing = ref(false)
const editContent = ref('')
const saving = ref(false)

const renderedMd = computed(() => {
  if (!readResult.value?.text) return ''
  return DOMPurify.sanitize(marked.parse(readResult.value.text, { async: false }) as string)
})

function resetViewer() {
  readResult.value = null
  editing.value = false
}

async function openFile(path: string) {
  if (!activeSource.value) return
  currentPath.value = path
  editing.value = false
  readLoading.value = true
  try {
    readResult.value = await knowledgeApi.read(activeSource.value.id, path)
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

const rawSrc = computed(() =>
  activeSource.value ? knowledgeApi.rawUrl(activeSource.value.id, currentPath.value) : '',
)

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
const pickerRoots = ref<string[]>([])
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
          <a v-if="['image', 'video', 'audio', 'pdf', 'binary', 'html'].includes(readResult.kind)" :href="rawSrc" target="_blank" class="dl-link">{{ t('knowledge.openRaw') }}</a>
          <el-button v-if="readResult.editable && !editing" size="small" type="primary" @click="startEdit">
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
            :src="rawSrc"
            class="kb-frame"
            sandbox="allow-same-origin"
          />

          <!-- pdf：原生预览 -->
          <iframe v-else-if="readResult.kind === 'pdf'" :src="rawSrc" class="kb-frame" />

          <!-- 图片 -->
          <div v-else-if="readResult.kind === 'image'" class="kb-center">
            <img :src="rawSrc" class="kb-img" :alt="currentPath" />
          </div>

          <!-- 视频/音频 -->
          <div v-else-if="['video', 'audio'].includes(readResult.kind)" class="kb-center">
            <video v-if="readResult.kind === 'video'" :src="rawSrc" controls class="kb-media" />
            <audio v-else :src="rawSrc" controls />
          </div>

          <!-- office：服务端转换 HTML -->
          <div v-else-if="['docx', 'xlsx', 'pptx'].includes(readResult.kind)" class="kb-md" v-html="readResult.html" />

          <!-- 其它：下载 -->
          <div v-else class="kb-center kb-binary">
            <p>{{ t('knowledge.binaryHint') }}</p>
            <a :href="rawSrc" target="_blank"><el-button size="small" type="primary">{{ t('knowledge.download') }}</el-button></a>
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
            :key="r"
            class="dp-row"
            @click="loadPicker(r)"
          >
            <span class="dp-name">{{ r }}</span>
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
.view-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
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
