<script setup lang="ts">
/**
 * Flow 自动化页（M06-1/2/15~18；dev-plan P14.5）：表单式编排 + 启停 + 运行/试运行 + 历史。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Plus, Sort } from '@element-plus/icons-vue'
import { flowApi, type FlowAction, type FlowBody, type FlowItem, type FlowRunItem } from '../api/flow'

const { t } = useI18n()

const items = ref<FlowItem[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    items.value = await flowApi.list()
  } finally {
    loading.value = false
  }
}

onMounted(load)

// ---------- 编排对话框 ----------
const dialog = ref(false)
const editing = ref<FlowItem | null>(null)
const saving = ref(false)
const form = reactive<FlowBody>({
  name: '',
  description: '',
  trigger_type: 'manual',
  trigger_config: {},
  actions: [],
  enabled: false,
  retry: 0,
  retry_interval: 60,
})
const cronText = ref('')
const hookEvent = ref('app_down')

const EVENT_OPTIONS = ['app_down', 'app_up', 'metric_alert', 'port_down', 'port_up', 'flow_failed']

function openCreate() {
  editing.value = null
  Object.assign(form, {
    name: '', description: '', trigger_type: 'manual', trigger_config: {},
    actions: [], enabled: false, retry: 0, retry_interval: 60,
  })
  cronText.value = '0 8 * * *'
  hookEvent.value = 'app_down'
  dialog.value = true
}

function openEdit(f: FlowItem) {
  editing.value = f
  Object.assign(form, {
    name: f.name, description: f.description, trigger_type: f.trigger_type,
    trigger_config: { ...f.trigger_config }, actions: f.actions.map((a) => ({ ...a, config: { ...(a.config ?? {}) } })),
    enabled: f.enabled, retry: f.retry, retry_interval: f.retry_interval,
  })
  cronText.value = String(f.trigger_config.cron ?? '0 8 * * *')
  hookEvent.value = String(f.trigger_config.event ?? 'app_down')
  dialog.value = true
}

function addAction(type: FlowAction['type']) {
  if (type === 'condition') form.actions.push({ type, expression: 'prev.status_code == 200' })
  else if (type === 'http')
    form.actions.push({ type, config: { method: 'GET', url: '', headers: {} as Record<string, string>, body: '' } })
  else form.actions.push({ type, config: { title: '', body: '', level: 'info' } })
}

function moveStep(i: number, dir: -1 | 1) {
  const j = i + dir
  if (j < 0 || j >= form.actions.length) return
  ;[form.actions[i], form.actions[j]] = [form.actions[j], form.actions[i]]
}

function buildBody(): FlowBody {
  const tc: Record<string, unknown> = { ...form.trigger_config }
  if (form.trigger_type === 'cron') tc.cron = cronText.value.trim()
  if (form.trigger_type === 'event') tc.event = hookEvent.value
  return { ...form, trigger_config: tc }
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning(t('flow.warnName'))
    return
  }
  saving.value = true
  try {
    if (editing.value) await flowApi.update(editing.value.id, buildBody())
    else await flowApi.create(buildBody())
    ElMessage.success(t('flow.saved'))
    dialog.value = false
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(f: FlowItem) {
  try {
    await flowApi.update(f.id, {
      name: f.name, description: f.description, trigger_type: f.trigger_type,
      trigger_config: f.trigger_config, actions: f.actions, enabled: f.enabled,
      retry: f.retry, retry_interval: f.retry_interval,
    })
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function remove(f: FlowItem) {
  const ok = await ElMessageBox.confirm(t('flow.confirmDelete', { name: f.name }), t('common.confirm'), {
    type: 'warning',
  }).then(
    () => true,
    () => false,
  )
  if (!ok) return
  await flowApi.remove(f.id)
  await load()
}

async function resetToken(f: FlowItem) {
  try {
    const r = await flowApi.resetToken(f.id)
    if (editing.value && editing.value.id === f.id) editing.value.webhook_token = r.webhook_token
    ElMessage.success(t('flow.tokenReset'))
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function run(f: FlowItem, dry = false) {
  try {
    const r = dry ? await flowApi.dryRun(f.id) : await flowApi.run(f.id)
    const runDetail = await flowApi.runDetail(r.run_id)
    history.value = [runDetail]
    historyFlow.value = `${f.name}${dry ? ' · dry-run' : ''}`
    historyDialog.value = true
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

// ---------- 历史 ----------
const historyDialog = ref(false)
const history = ref<FlowRunItem[]>([])
const historyFlow = ref('')

async function showHistory(f: FlowItem) {
  history.value = await flowApi.runs(f.id)
  historyFlow.value = f.name
  historyDialog.value = true
}

function stepLabel(s: Record<string, unknown>): string {
  if (s.skipped) return t('flow.stepSkipped')
  if (s.dry_run) return t('flow.stepDry')
  if (s.error) return `${s.error}`
  if (s.type === 'condition') return `${s.expression} → ${s.result}`
  if (s.type === 'http') {
    const req = (s.request ?? {}) as Record<string, string>
    return `${req.method ?? ''} ${req.url ?? ''}`
  }
  return String(s.type ?? '')
}

// ---------- 触发器文案 ----------
function triggerLabel(f: FlowItem): string {
  const cfg = f.trigger_config
  if (f.trigger_type === 'cron') return `${t('flow.trg.cron')}: ${cfg.cron ?? ''}`
  if (f.trigger_type === 'webhook') return t('flow.trg.webhook')
  if (f.trigger_type === 'event') return `${t('flow.trg.event')}: ${t(`notify.ev.${cfg.event}`)}`
  return t('flow.trg.manual')
}

const sorted = computed(() => [...items.value].sort((a, b) => (b.enabled ? 1 : 0) - (a.enabled ? 1 : 0)))
</script>

<template>
  <div class="flow-page fade-up">
    <header class="page-head">
      <p class="muted">{{ t('flow.hint') }}</p>
      <el-button type="primary" class="btn-gradient" size="small" :icon="Plus" @click="openCreate">
        {{ t('flow.add') }}
      </el-button>
    </header>

    <section class="glass list-card">
      <el-table :data="sorted" size="default" v-loading="loading">
        <el-table-column :label="t('flow.colName')" min-width="180">
          <template #default="{ row }">
            <div class="f-name">{{ row.name }}</div>
            <div class="f-desc">{{ triggerLabel(row) }}</div>
          </template>
        </el-table-column>
        <el-table-column :label="t('flow.colActions')" min-width="150">
          <template #default="{ row }">
            <el-tag v-for="(a, i) in row.actions" :key="i" size="small" class="act-tag">
              {{ t(`flow.act.${a.type}`) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('flow.colLastRun')" width="160">
          <template #default="{ row }">
            {{ row.last_run_at ? new Date(row.last_run_at).toLocaleString() : '-' }}
          </template>
        </el-table-column>
        <el-table-column :label="t('flow.colEnabled')" width="80" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" size="small" @change="toggleEnabled(row)" />
          </template>
        </el-table-column>
        <el-table-column :label="t('ports.colActions')" width="230" align="right">
          <template #default="{ row }">
            <el-button link size="small" @click="run(row)">{{ t('flow.run') }}</el-button>
            <el-button link size="small" @click="run(row, true)">{{ t('flow.dryRun') }}</el-button>
            <el-button link size="small" @click="showHistory(row)">{{ t('flow.history') }}</el-button>
            <el-button link size="small" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
            <el-button link size="small" type="danger" :icon="Delete" @click="remove(row)" />
          </template>
        </el-table-column>
        <template #empty>{{ t('flow.empty') }}</template>
      </el-table>
    </section>

    <!-- 编排对话框 -->
    <el-dialog append-to-body v-model="dialog" :title="editing ? t('flow.edit') : t('flow.add')" width="640px" top="4vh">
      <el-form label-width="100px">
        <el-form-item :label="t('flow.fld.name')"><el-input v-model="form.name" maxlength="60" /></el-form-item>
        <el-form-item :label="t('apps.fieldDesc')">
          <el-input v-model="form.description" :placeholder="t('flow.descPh')" />
        </el-form-item>
        <el-form-item :label="t('flow.trigger')">
          <el-radio-group v-model="form.trigger_type" size="small">
            <el-radio-button value="manual">{{ t('flow.trg.manual') }}</el-radio-button>
            <el-radio-button value="cron">{{ t('flow.trg.cron') }}</el-radio-button>
            <el-radio-button value="webhook">{{ t('flow.trg.webhook') }}</el-radio-button>
            <el-radio-button value="event">{{ t('flow.trg.event') }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.trigger_type === 'cron'" :label="t('flow.cronExpr')">
          <el-input v-model="cronText" placeholder="0 8 * * *" style="width: 200px" />
        </el-form-item>
        <el-form-item v-if="form.trigger_type === 'event'" :label="t('flow.event')">
          <el-select v-model="hookEvent" style="width: 240px">
            <el-option v-for="e in EVENT_OPTIONS" :key="e" :label="t(`notify.ev.${e}`)" :value="e" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.trigger_type === 'webhook' && editing?.webhook_token" label="Token">
          <code class="mono">{{ editing.webhook_token }}</code>
          <el-button link size="small" style="margin-left: 8px" @click="resetToken(editing)">
            {{ t('flow.resetToken') }}
          </el-button>
        </el-form-item>
      </el-form>

      <header class="act-head">
        <h4>{{ t('flow.actionsTitle') }}</h4>
        <div class="add-btns">
          <el-button size="small" :icon="Plus" @click="addAction('condition')">{{ t('flow.act.condition') }}</el-button>
          <el-button size="small" :icon="Plus" @click="addAction('http')">{{ t('flow.act.http') }}</el-button>
          <el-button size="small" :icon="Plus" @click="addAction('notify')">{{ t('flow.act.notify') }}</el-button>
        </div>
      </header>
      <div v-if="!form.actions.length" class="muted">{{ t('flow.noActions') }}</div>
      <div v-for="(a, i) in form.actions" :key="i" class="act-card">
        <div class="act-head-row">
          <span class="act-idx">{{ i + 1 }}</span>
          <el-tag size="small">{{ t(`flow.act.${a.type}`) }}</el-tag>
          <span class="act-ops">
            <el-button link size="small" :icon="Sort" @click="moveStep(i, -1)" />
            <el-button link size="small" :icon="Sort" style="transform: rotate(180deg)" @click="moveStep(i, 1)" />
            <el-button link size="small" type="danger" :icon="Delete" @click="form.actions.splice(i, 1)" />
          </span>
        </div>
        <el-input
          v-if="a.type === 'condition'"
          v-model="a.expression"
          size="small"
          :placeholder="t('flow.exprPh')"
        />
        <template v-if="a.type === 'http'">
          <div class="act-grid">
            <el-select v-model="a.config!.method" size="small" style="width: 100px">
              <el-option v-for="m in ['GET', 'POST', 'PUT', 'DELETE']" :key="m" :label="m" :value="m" />
            </el-select>
            <el-input v-model="a.config!.url" size="small" :placeholder="t('flow.urlPh')" />
          </div>
        </template>
        <template v-if="a.type === 'notify'">
          <el-input v-model="a.config!.title" size="small" :placeholder="t('flow.notifyTitlePh')" style="margin-bottom: 6px" />
          <el-input v-model="a.config!.body" size="small" :placeholder="t('flow.notifyBodyPh')" />
        </template>
      </div>

      <div class="retry-row">
        <span>{{ t('flow.retry') }}</span>
        <el-input-number v-model="form.retry" :min="0" :max="10" size="small" />
        <span>{{ t('flow.retryInterval') }}</span>
        <el-input-number v-model="form.retry_interval" :min="5" :max="3600" size="small" />
        <el-checkbox v-model="form.enabled">{{ t('flow.enabledOnSave') }}</el-checkbox>
      </div>

      <template #footer>
        <el-button @click="dialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" class="btn-gradient" :loading="saving" @click="save">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <!-- 运行历史 -->
    <el-dialog append-to-body v-model="historyDialog" :title="t('flow.historyTitle', { name: historyFlow })" width="680px">
      <div v-if="!history.length" class="muted">{{ t('flow.noRuns') }}</div>
      <div v-for="r in history" :key="r.id" class="run-card">
        <div class="run-head">
          <el-tag :type="r.status === 'success' ? 'success' : r.status === 'failed' ? 'danger' : 'info'" size="small">
            {{ r.status }}
          </el-tag>
          <span class="run-meta">
            {{ r.trigger }} · {{ r.duration_ms ?? '-' }}ms ·
            {{ r.started_at ? new Date(r.started_at).toLocaleString() : '' }}
          </span>
        </div>
        <div v-for="(s, i) in r.steps" :key="i" class="run-step mono">{{ stepLabel(s) }}</div>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.flow-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.muted {
  color: var(--p-muted);
  font-size: 12.5px;
}
.list-card {
  padding: 10px 14px 14px;
  border-radius: 12px;
}
.f-name {
  font-weight: 600;
}
.f-desc {
  font-size: 12px;
  color: var(--p-muted);
}
.act-tag {
  margin-right: 6px;
}
.act-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 10px 0 8px;
}
.add-btns {
  display: flex;
  gap: 6px;
}
.act-head h4 {
  margin: 0;
  font-size: 13px;
}
.act-card {
  border: 1px dashed rgba(127, 127, 127, 0.4);
  border-radius: 10px;
  padding: 10px;
  margin-bottom: 8px;
}
.act-head-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.act-idx {
  font-weight: 700;
}
.act-ops {
  margin-left: auto;
}
.act-grid {
  display: flex;
  gap: 8px;
}
.retry-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  font-size: 13px;
}
.mono {
  font-family: ui-monospace, monospace;
  font-size: 12px;
  word-break: break-all;
}
.run-card {
  border-bottom: 1px dashed rgba(127, 127, 127, 0.3);
  padding: 8px 0;
  margin-bottom: 8px;
}
.run-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}
.run-meta {
  color: var(--p-muted);
  font-size: 12px;
}
.run-step {
  padding: 3px 8px;
  background: rgba(127, 127, 127, 0.08);
  border-radius: 6px;
  margin-bottom: 4px;
}
</style>
