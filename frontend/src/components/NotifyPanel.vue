<script setup lang="ts">
/**
 * 通知中心设置面板（M09-4~12；dev-plan P9.1/P9.3）。
 *
 * 渠道：八类渠道 CRUD + 一键测试发送（config 敏感字段回传掩码，****** 表示保持原值）；
 * 规则：事件×渠道路由矩阵（PUT 全量保存）+ 规则级免打扰时段（HH:MM，可跨午夜）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'
import {
  notifyApi,
  type ChannelType,
  type NotifyChannel,
  type NotifyEvent,
  type NotifyRule,
} from '../api/notify'

const { t } = useI18n()

// ---------- 渠道 ----------

const channels = ref<NotifyChannel[]>([])
const loading = ref(false)

/** 各渠道的 config 字段定义（type=password 的字段为敏感，回传为 ******） */
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
</script>

<template>
  <div class="notify-panel" v-loading="loading">
    <!-- 渠道 -->
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

    <!-- 规则矩阵 -->
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

    <!-- 渠道编辑对话框 -->
    <el-dialog v-model="dialog" :title="editing ? t('notify.editChannel') : t('notify.addChannel')" width="460px">
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
  margin-top: 8px;
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
}
.type-tag {
  flex-shrink: 0;
}
.channel-name {
  font-size: 13px;
  font-weight: 600;
}
.channel-ops {
  display: flex;
  align-items: center;
  gap: 8px;
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
</style>
