<script setup lang="ts">
/**
 * 通知中心设置面板（M09 + M17-14/15 + M07-6；dev-plan P9/P10.3/P10.5）。
 *
 * tab1 通知路由：八类渠道 CRUD + 测试发送（敏感字段 ****** 掩码保持原值）+ 事件×渠道路由矩阵 + 免打扰时段；
 * tab2 阈值告警：指标越限持续 N 分钟触发（状态机在 services/alerts.py），规则 CRUD + 测试 + 事件历史；
 * tab3 证书监控：monitor.cert_hosts 域名维护 + 到期天数分级（≤1 error / ≤7 warn / ≤30 info）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'
import {
  monitorApi,
  type AlertEvent,
  type AlertRule,
  type AlertRuleBody,
  type AlertMetric,
  type CertInfo,
} from '../api/monitor'
import { useSettingsStore } from '../stores/settings'
import {
  notifyApi,
  type ChannelType,
  type NotifyChannel,
  type NotifyEvent,
  type NotifyRule,
} from '../api/notify'

const { t } = useI18n()
const settingsStore = useSettingsStore()
const tab = ref<'routes' | 'alerts' | 'certs'>('routes')

// ---------- 渠道 ----------

const channels = ref<NotifyChannel[]>([])
const loading = ref(false)

interface FieldDef {
  key: string
  label: string
  type?: 'text' | 'password' | 'switch'
  ph?: string
}

const CHANNEL_FIELDS: Record<ChannelType, FieldDef[]> = {
  bark: [
    { key: 'server', label: 'notify.fld.server', ph: 'https://api.day.app' },
    { key: 'device_key', label: 'notify.fld.deviceKey', type: 'password' },
  ],
  telegram: [
    { key: 'bot_token', label: 'notify.fld.botToken', type: 'password' },
    { key: 'chat_id', label: 'notify.fld.chatId' },
  ],
  smtp: [
    { key: 'host', label: 'notify.fld.smtpHost', ph: 'smtp.example.com' },
    { key: 'port', label: 'notify.fld.smtpPort', ph: '465' },
    { key: 'username', label: 'notify.fld.smtpUser' },
    { key: 'password', label: 'notify.fld.smtpPassword', type: 'password' },
    { key: 'to_addrs', label: 'notify.fld.toAddrs', ph: 'a@x.com, b@x.com' },
    { key: 'use_tls', label: 'notify.fld.useTls', type: 'switch' },
  ],
  webhook: [{ key: 'url', label: 'notify.fld.url', ph: 'https://…/hook' }],
  wecom: [{ key: 'url', label: 'notify.fld.url', ph: 'https://qyapi.weixin.qq.com/…' }],
  dingtalk: [{ key: 'url', label: 'notify.fld.url', ph: 'https://oapi.dingtalk.com/…' }],
  feishu: [{ key: 'url', label: 'notify.fld.url', ph: 'https://open.feishu.cn/…' }],
  ntfy: [
    { key: 'server', label: 'notify.fld.server', ph: 'https://ntfy.sh' },
    { key: 'topic', label: 'notify.fld.topic' },
  ],
}

const TYPE_LABEL: Record<ChannelType, string> = {
  bark: 'Bark',
  telegram: 'Telegram',
  smtp: 'SMTP',
  webhook: 'Webhook',
  wecom: '企业微信',
  dingtalk: '钉钉',
  feishu: '飞书',
  ntfy: 'ntfy',
}

async function load() {
  loading.value = true
  try {
    channels.value = await notifyApi.channels()
    await loadRules()
  } finally {
    loading.value = false
  }
}

onMounted(load)

const dialog = ref(false)
const editing = ref<NotifyChannel | null>(null)
const form = reactive<{ type: ChannelType; name: string; enabled: boolean; config: Record<string, unknown> }>({
  type: 'webhook',
  name: '',
  enabled: true,
  config: {},
})

function fieldsFor(type: ChannelType): FieldDef[] {
  return CHANNEL_FIELDS[type] ?? []
}

function openCreate() {
  editing.value = null
  form.type = 'webhook'
  form.name = ''
  form.enabled = true
  form.config = {}
  dialog.value = true
}

function openEdit(c: NotifyChannel) {
  editing.value = c
  form.type = c.type
  form.name = c.name
  form.enabled = c.enabled
  form.config = { ...c.config }
  dialog.value = true
}

function onTypeChange(type: ChannelType) {
  form.type = type
  form.config = {}
}

/** smtp 的 to_addrs 以逗号分隔输入，保存拆数组 */
function buildPayload(): Omit<NotifyChannel, 'id'> {
  const config: Record<string, unknown> = { ...form.config }
  if (form.type === 'smtp' && typeof config.to_addrs === 'string') {
    config.to_addrs = (config.to_addrs as string)
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
  }
  if (form.type === 'smtp') config.port = Number(config.port || 25)
  return { type: form.type, name: form.name, enabled: form.enabled, config }
}

async function saveChannel() {
  if (!form.name.trim()) {
    ElMessage.warning(t('notify.warnName'))
    return
  }
  try {
    if (editing.value) await notifyApi.updateChannel(editing.value.id, buildPayload())
    else await notifyApi.createChannel(buildPayload())
    ElMessage.success(t('notify.saved'))
    dialog.value = false
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function toggleChannel(c: NotifyChannel) {
  try {
    await notifyApi.updateChannel(c.id, { type: c.type, name: c.name, enabled: c.enabled, config: c.config })
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function testChannel(c: NotifyChannel) {
  try {
    const r = await notifyApi.testChannel(c.id)
    if (r.sent) ElMessage.success(t('notify.testOk'))
    else ElMessage.error(t('notify.testFail'))
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function removeChannel(c: NotifyChannel) {
  const ok = await ElMessageBox.confirm(t('notify.confirmDelete', { name: c.name }), t('common.confirm'), {
    type: 'warning',
  }).then(
    () => true,
    () => false,
  )
  if (!ok) return
  await notifyApi.deleteChannel(c.id)
  ElMessage.success(t('notify.deleted'))
  await load()
}

// ---------- 规则矩阵（M09-10/11） ----------

const EVENTS: NotifyEvent[] = [
  'app_down',
  'app_up',
  'metric_alert',
  'port_down',
  'port_up',
  'flow_failed',
  'system',
]

interface RuleDraft {
  event: NotifyEvent
  channel_ids: number[]
  enabled: boolean
  quiet_start: string | null
  quiet_end: string | null
}

const rules = ref<RuleDraft[]>([])
const savingRules = ref(false)
const activeChannels = computed(() => channels.value.filter((c) => c.enabled))

async function loadRules() {
  const rows: NotifyRule[] = await notifyApi.rules()
  rules.value = EVENTS.map(
    (ev) => rows.find((r) => r.event === ev) ?? {
      event: ev,
      channel_ids: [],
      enabled: true,
      quiet_start: null,
      quiet_end: null,
    },
  )
}

function toggleRoute(rule: RuleDraft, cid: number, on: boolean) {
  rule.channel_ids = on ? [...rule.channel_ids, cid] : rule.channel_ids.filter((x) => x !== cid)
}

async function saveRules() {
  savingRules.value = true
  try {
    await notifyApi.replaceRules(rules.value.map((r) => ({ ...r })))
    ElMessage.success(t('notify.rulesSaved'))
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    savingRules.value = false
  }
}

// ---------- 阈值告警（M17-14/15；P10.3） ----------

const alertRules = ref<AlertRule[]>([])
const alertEvents = ref<AlertEvent[]>([])
const alertDialog = ref(false)
const alertEditing = ref<AlertRule | null>(null)
const savingAlert = ref(false)

const METRIC_OPTIONS: { value: AlertMetric; label: string }[] = [
  { value: 'cpu', label: 'CPU %' },
  { value: 'mem', label: 'Mem %' },
  { value: 'disk', label: 'Disk %' },
  { value: 'disk_io', label: 'Disk IOPS' },
  { value: 'temp', label: 'Temp °C' },
]

const alertForm = reactive<{
  name: string
  metric: AlertMetric
  target: string
  op: '>' | '<'
  threshold: number
  duration_min: number
  level: 'warn' | 'error'
  enabled: boolean
}>({ name: '', metric: 'cpu', target: '', op: '>', threshold: 80, duration_min: 5, level: 'warn', enabled: true })

async function loadAlerts() {
  alertRules.value = await monitorApi.alertRules()
  alertEvents.value = await monitorApi.alertEvents('30d')
}

function openAlertCreate() {
  alertEditing.value = null
  Object.assign(alertForm, {
    name: '', metric: 'cpu' as AlertMetric, target: '', op: '>' as const,
    threshold: 80, duration_min: 5, level: 'warn' as const, enabled: true,
  })
  alertDialog.value = true
}

function openAlertEdit(r: AlertRule) {
  alertEditing.value = r
  Object.assign(alertForm, {
    name: r.name, metric: r.metric, target: r.target ?? '', op: r.op,
    threshold: r.threshold, duration_min: r.duration_min, level: r.level, enabled: r.enabled,
  })
  alertDialog.value = true
}

function alertBody(): AlertRuleBody {
  return {
    name: alertForm.name,
    metric: alertForm.metric,
    target: alertForm.target.trim() || null,
    op: alertForm.op,
    threshold: alertForm.threshold,
    duration_min: alertForm.duration_min,
    level: alertForm.level,
    enabled: alertForm.enabled,
  }
}

async function saveAlert() {
  savingAlert.value = true
  try {
    if (alertEditing.value) await monitorApi.updateAlertRule(alertEditing.value.id, alertBody())
    else await monitorApi.createAlertRule(alertBody())
    ElMessage.success(t('notify.alert.saved'))
    alertDialog.value = false
    await loadAlerts()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    savingAlert.value = false
  }
}

async function toggleAlert(r: AlertRule) {
  try {
    await monitorApi.updateAlertRule(r.id, {
      name: r.name, metric: r.metric, target: r.target, op: r.op, threshold: r.threshold,
      duration_min: r.duration_min, level: r.level, enabled: r.enabled,
    })
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function testAlert(r: AlertRule) {
  try {
    const res = await monitorApi.testAlertRule(r.id)
    if (res.current === null) ElMessage.warning(t('notify.alert.noValue'))
    else if (res.violated) ElMessage.warning(t('notify.alert.wouldFire', { current: res.current }))
    else ElMessage.success(t('notify.alert.notViolated', { current: res.current }))
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function removeAlert(r: AlertRule) {
  const ok = await ElMessageBox.confirm(t('notify.alert.confirmDelete', { name: r.name }), t('common.confirm'), {
    type: 'warning',
  }).then(
    () => true,
    () => false,
  )
  if (!ok) return
  await monitorApi.deleteAlertRule(r.id)
  await loadAlerts()
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

// ---------- 证书监控（M07-6；P10.5） ----------

const certHostsInput = ref('')
const certRows = ref<CertInfo[]>([])
const savingCerts = ref(false)

async function loadCerts() {
  certRows.value = await monitorApi.certs().catch(() => [])
}

async function saveCertHosts() {
  savingCerts.value = true
  try {
    await monitorApi.saveCertHosts(
      certHostsInput.value
        .split(/[\n,]/)
        .map((s) => s.trim())
        .filter(Boolean),
    )
    ElMessage.success(t('notify.cert.saved'))
    await loadCerts()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    savingCerts.value = false
  }
}

async function onTab(name: string | number) {
  if (name === 'alerts') await loadAlerts()
  if (name === 'certs') {
    // 回填已保存的域名（设置键 monitor.cert_hosts）
    await settingsStore.load()
    const saved = settingsStore.map['monitor.cert_hosts'] as string[] | undefined
    if (saved?.length && !certHostsInput.value) certHostsInput.value = saved.join('\n')
    await loadCerts()
  }
}
</script>

<template>
  <div class="notify-panel" v-loading="loading">
    <el-tabs v-model="tab" @tab-change="onTab">
      <!-- ======== tab1 通知路由（P9） ======== -->
      <el-tab-pane :label="t('notify.tabRoutes')" name="routes">
        <header class="sec-head">
          <div>
            <h4>{{ t('notify.channelsTitle') }}</h4>
            <p>{{ t('notify.channelsHint') }}</p>
          </div>
          <el-button type="primary" class="btn-gradient" @click="openCreate">{{ t('notify.addChannel') }}</el-button>
        </header>

        <div v-if="channels.length === 0" class="empty">{{ t('notify.noChannels') }}</div>
        <div v-else class="channel-list">
          <div v-for="c in channels" :key="c.id" class="channel-card">
            <div class="channel-main">
              <el-tag size="small" effect="dark" class="type-tag">{{ TYPE_LABEL[c.type] }}</el-tag>
              <span class="channel-name">{{ c.name }}</span>
            </div>
            <div class="channel-ops">
              <el-switch v-model="c.enabled" size="small" @change="toggleChannel(c)" />
              <el-button link size="small" @click="testChannel(c)">{{ t('notify.test') }}</el-button>
              <el-button link size="small" @click="openEdit(c)">{{ t('common.edit') }}</el-button>
              <el-button link size="small" type="danger" :icon="Delete" @click="removeChannel(c)" />
            </div>
          </div>
        </div>

        <header class="sec-head rules-head">
          <div>
            <h4>{{ t('notify.rulesTitle') }}</h4>
            <p>{{ t('notify.rulesHint') }}</p>
          </div>
          <el-button type="primary" class="btn-gradient" :loading="savingRules" @click="saveRules">
            {{ t('common.save') }}
          </el-button>
        </header>

        <el-table :data="rules" size="small">
          <el-table-column :label="t('notify.colEvent')" min-width="130">
            <template #default="{ row }">{{ t(`notify.ev.${row.event}`) }}</template>
          </el-table-column>
          <el-table-column
            v-for="c in activeChannels"
            :key="c.id"
            :label="c.name"
            min-width="90"
            align="center"
          >
            <template #default="{ row }">
              <el-checkbox
                :model-value="row.channel_ids.includes(c.id)"
                @update:model-value="(v: boolean) => toggleRoute(row, c.id, v)"
              />
            </template>
          </el-table-column>
          <el-table-column :label="t('notify.colQuiet')" min-width="190">
            <template #default="{ row }">
              <div class="quiet-cell">
                <el-time-select
                  v-model="row.quiet_start"
                  :placeholder="t('notify.quietStart')"
                  start="00:00"
                  step="00:30"
                  end="23:30"
                  clearable
                  size="small"
                  style="width: 100px"
                />
                <span>~</span>
                <el-time-select
                  v-model="row.quiet_end"
                  :placeholder="t('notify.quietEnd')"
                  start="00:00"
                  step="00:30"
                  end="23:30"
                  clearable
                  size="small"
                  style="width: 100px"
                />
              </div>
            </template>
          </el-table-column>
        </el-table>
        <p class="quiet-hint">{{ t('notify.quietHint') }}</p>
      </el-tab-pane>

      <!-- ======== tab2 阈值告警（P10.3） ======== -->
      <el-tab-pane :label="t('notify.alert.tabTitle')" name="alerts">
        <header class="sec-head">
          <div>
            <h4>{{ t('notify.alert.rulesTitle') }}</h4>
            <p>{{ t('notify.alert.rulesHint') }}</p>
          </div>
          <el-button type="primary" class="btn-gradient" @click="openAlertCreate">
            {{ t('notify.alert.addRule') }}
          </el-button>
        </header>

        <div v-if="alertRules.length === 0" class="empty">{{ t('notify.alert.noRules') }}</div>
        <div v-else class="channel-list">
          <div v-for="r in alertRules" :key="r.id" class="channel-card">
            <div class="channel-main">
              <el-tag size="small" :type="r.level === 'error' ? 'danger' : 'warning'" class="type-tag">
                {{ t(`notify.alert.level.${r.level}`) }}
              </el-tag>
              <span class="channel-name">{{ r.name || r.metric }}</span>
              <span class="alert-desc">
                {{ r.metric }} {{ r.op }} {{ r.threshold }} · {{ r.duration_min }}min
                <template v-if="r.target"> · {{ r.target }}</template>
              </span>
            </div>
            <div class="channel-ops">
              <el-switch v-model="r.enabled" size="small" @change="toggleAlert(r)" />
              <el-button link size="small" @click="testAlert(r)">{{ t('notify.test') }}</el-button>
              <el-button link size="small" @click="openAlertEdit(r)">{{ t('common.edit') }}</el-button>
              <el-button link size="small" type="danger" :icon="Delete" @click="removeAlert(r)" />
            </div>
          </div>
        </div>

        <header class="sec-head rules-head">
          <div>
            <h4>{{ t('notify.alert.eventsTitle') }}</h4>
            <p>{{ t('notify.alert.eventsHint') }}</p>
          </div>
        </header>
        <div v-if="alertEvents.length === 0" class="empty">{{ t('notify.alert.noEvents') }}</div>
        <div v-else class="channel-list">
          <div v-for="e in alertEvents" :key="e.id" class="event-row">
            <span class="ev-dot" :class="e.level" />
            <span class="ev-title">{{ e.title }}</span>
            <span class="ev-time">{{ fmtTime(e.created_at) }}</span>
          </div>
        </div>

        <el-dialog append-to-body
          v-model="alertDialog"
          :title="alertEditing ? t('notify.alert.editRule') : t('notify.alert.addRule')"
          width="460px"

        >
          <el-form label-width="110px">
            <el-form-item :label="t('notify.fld.name')">
              <el-input v-model="alertForm.name" maxlength="50" :placeholder="t('notify.alert.namePh')" />
            </el-form-item>
            <el-form-item :label="t('notify.colType')">
              <el-select v-model="alertForm.metric" style="width: 100%">
                <el-option v-for="m in METRIC_OPTIONS" :key="m.value" :label="m.label" :value="m.value" />
              </el-select>
            </el-form-item>
            <el-form-item
              v-if="alertForm.metric === 'disk' || alertForm.metric === 'temp'"
              :label="t('notify.alert.target')"
            >
              <el-input v-model="alertForm.target" :placeholder="t('notify.alert.targetPh')" />
            </el-form-item>
            <el-form-item :label="t('notify.alert.condition')">
              <div class="cond-row">
                <el-select v-model="alertForm.op" style="width: 70px">
                  <el-option label=">" value=">" />
                  <el-option label="<" value="<" />
                </el-select>
                <el-input-number v-model="alertForm.threshold" :min="-100" :max="100000" style="flex: 1" />
              </div>
            </el-form-item>
            <el-form-item :label="t('notify.alert.duration')">
              <el-input-number v-model="alertForm.duration_min" :min="1" :max="1440" style="width: 100%" />
            </el-form-item>
            <el-form-item :label="t('users.role')">
              <el-radio-group v-model="alertForm.level">
                <el-radio-button value="warn">{{ t('notify.alert.level.warn') }}</el-radio-button>
                <el-radio-button value="error">{{ t('notify.alert.level.error') }}</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item :label="t('notify.fld.enabled')">
              <el-switch v-model="alertForm.enabled" />
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="alertDialog = false">{{ t('common.cancel') }}</el-button>
            <el-button type="primary" class="btn-gradient" :loading="savingAlert" @click="saveAlert">
              {{ t('common.save') }}
            </el-button>
          </template>
        </el-dialog>
      </el-tab-pane>

      <!-- ======== tab3 证书监控（P10.5） ======== -->
      <el-tab-pane :label="t('notify.cert.tabTitle')" name="certs">
        <header class="sec-head">
          <div>
            <h4>{{ t('notify.cert.hostsTitle') }}</h4>
            <p>{{ t('notify.cert.hostsHint') }}</p>
          </div>
          <el-button type="primary" class="btn-gradient" :loading="savingCerts" @click="saveCertHosts">
            {{ t('common.save') }}
          </el-button>
        </header>
        <el-input v-model="certHostsInput" type="textarea" :rows="3" :placeholder="t('notify.cert.hostsPh')" />
        <header class="sec-head rules-head">
          <div>
            <h4>{{ t('notify.cert.listTitle') }}</h4>
          </div>
          <el-button size="small" @click="loadCerts">{{ t('notify.cert.refresh') }}</el-button>
        </header>
        <div v-if="certRows.length === 0" class="empty">{{ t('notify.cert.emptyList') }}</div>
        <div v-else class="channel-list">
          <div v-for="c in certRows" :key="c.host" class="channel-card">
            <span class="channel-name">{{ c.host }}</span>
            <span v-if="c.error" class="cert-lvl bad">{{ c.error }}</span>
            <span v-else-if="c.level === 'ok'" class="cert-lvl good">
              {{ t('notify.cert.days', { days: c.days_left }) }} · {{ c.not_after }}
            </span>
            <span v-else class="cert-lvl" :class="c.level">
              {{ t('notify.cert.days', { days: c.days_left }) }} · {{ c.not_after }}
            </span>
          </div>
        </div>
        <p class="quiet-hint">{{ t('notify.cert.checkHint') }}</p>
      </el-tab-pane>
    </el-tabs>

    <!-- 渠道编辑对话框 -->
    <el-dialog append-to-body
      v-model="dialog"
      :title="editing ? t('notify.editChannel') : t('notify.addChannel')"
      width="460px"

    >
      <el-form label-width="110px">
        <el-form-item :label="t('notify.colType')">
          <el-select :model-value="form.type" :disabled="!!editing" style="width: 100%" @update:model-value="onTypeChange">
            <el-option v-for="(label, ty) in TYPE_LABEL" :key="ty" :label="label" :value="ty" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('notify.fld.name')">
          <el-input v-model="form.name" maxlength="50" />
        </el-form-item>
        <el-form-item v-for="f in fieldsFor(form.type)" :key="f.key" :label="t(f.label)">
          <el-switch v-if="f.type === 'switch'" v-model="form.config[f.key]" />
          <el-input
            v-else
            v-model="form.config[f.key]"
            :type="f.type === 'password' ? 'password' : 'text'"
            :placeholder="f.ph"
            clearable
          />
        </el-form-item>
        <el-form-item :label="t('notify.fld.enabled')">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" class="btn-gradient" @click="saveChannel">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.notify-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.sec-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}
.sec-head h4 {
  margin: 0 0 2px;
  font-size: 14px;
}
.sec-head p {
  margin: 0;
  font-size: 12.5px;
  color: var(--p-muted);
}
.rules-head {
  margin-top: 14px;
}
.empty {
  color: var(--p-muted);
  font-size: 13px;
  padding: 10px 0;
}
.channel-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.channel-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 12px;
  border-radius: 10px;
  background: var(--p-card, rgba(127, 127, 127, 0.08));
}
.channel-main {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex-wrap: wrap;
}
.type-tag {
  flex-shrink: 0;
}
.channel-name {
  font-size: 13px;
  font-weight: 600;
}
.alert-desc {
  font-size: 12px;
  color: var(--p-muted);
}
.channel-ops {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.quiet-cell {
  display: flex;
  align-items: center;
  gap: 4px;
}
.quiet-hint {
  margin: 0;
  font-size: 12px;
  color: var(--p-muted);
}
.event-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 8px;
  background: var(--p-card, rgba(127, 127, 127, 0.08));
  font-size: 12.5px;
}
.ev-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.ev-dot.info { background: var(--el-color-info); }
.ev-dot.warn { background: var(--el-color-warning); }
.ev-dot.error { background: var(--el-color-danger); }
.ev-title {
  flex: 1;
  min-width: 0;
}
.ev-time {
  color: var(--p-muted);
  flex-shrink: 0;
}
.cond-row {
  display: flex;
  gap: 8px;
  width: 100%;
}
.cert-lvl.good { color: var(--el-color-success); }
.cert-lvl.info { color: var(--el-color-success); }
.cert-lvl.warn { color: var(--el-color-warning); }
.cert-lvl.bad,
.cert-lvl.error { color: var(--el-color-danger); }
</style>
