<script setup lang="ts">
/**
 * AI 助手页（M05-4~13；dev-plan P13）。
 * 多会话管理 + WS 流式输出 + Markdown 渲染 + 意图导航跳转 + 快捷指令 + 应用草稿 + Provider 设置。
 */
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Edit, Plus, Setting } from '@element-plus/icons-vue'
import { marked } from 'marked'
import { aiApi, type AiConversationItem, type AiMessageItem, type AiProvider } from '../api/ai'
import { portalApi, type PortalApp } from '../api/portal'
import { settingsApi } from '../api/settings'
import { buildAiWsUrl } from '../utils/aiWs'

const { t } = useI18n()
const router = useRouter()

// ---------- 会话 ----------
const conversations = ref<AiConversationItem[]>([])
const activeId = ref<number | null>(null)
const messages = ref<AiMessageItem[]>([])
const input = ref('')
const streaming = ref(false)
const streamText = ref('')
const apps = ref<PortalApp[]>([])

const QUICK_PROMPTS = computed(() => [
  t('ai.quick.navigate'),
  t('ai.quick.status'),
  t('ai.quick.translate'),
  t('ai.quick.summary'),
])

async function loadConversations() {
  conversations.value = await aiApi.conversations()
  if (conversations.value.length && activeId.value === null) {
    await openConversation(conversations.value[0].id)
  }
}

async function newConversation() {
  // title 传空 → 后端默认「新对话」；WS 首条消息自动以内容截断为题
  const c = await aiApi.createConversation('')
  conversations.value.unshift(c)
  activeId.value = c.id
  messages.value = []
}

async function openConversation(id: number) {
  activeId.value = id
  messages.value = await aiApi.messages(id)
  streamText.value = ''
}

async function renameConversation(c: AiConversationItem) {
  const { value } = await ElMessageBox.prompt(t('ai.renamePrompt'), t('ai.rename'), {
    inputValue: c.title,
  })
  await aiApi.renameConversation(c.id, value)
  c.title = value
}

async function removeConversation(c: AiConversationItem) {
  const ok = await ElMessageBox.confirm(t('ai.confirmDelete', { name: c.title }), t('common.confirm'), {
    type: 'warning',
  }).then(
    () => true,
    () => false,
  )
  if (!ok) return
  await aiApi.deleteConversation(c.id)
  if (activeId.value === c.id) {
    activeId.value = null
    messages.value = []
  }
  await loadConversations()
}

// ---------- WS 流式对话 ----------
let ws: WebSocket | null = null

function renderMd(text: string): string {
  return marked.parse(text, { async: false }) as string
}

function sendQuick(text: string) {
  input.value = text
  void send()
}

function send() {
  const content = input.value.trim()
  if (!content || streaming.value) return
  if (!activeId.value) {
    ElMessage.warning(t('ai.needConversation'))
    return
  }
  messages.value.push({
    id: Date.now(),
    role: 'user',
    content,
    created_at: new Date().toISOString(),
  })
  input.value = ''
  streaming.value = true
  streamText.value = ''

  ws = new WebSocket(buildAiWsUrl(authToken()))
  ws.onmessage = (ev) => {
    const frame = JSON.parse(ev.data)
    if (frame.type === 'delta') {
      streamText.value += frame.delta
      scrollBottom()
    } else if (frame.type === 'done') {
      messages.value.push({
        id: Date.now(),
        role: 'assistant',
        content: frame.content,
        created_at: new Date().toISOString(),
      })
      streamText.value = ''
      streaming.value = false
      // 意图导航（M05-10）：{action:"navigate", app_id}
      if (frame.navigate_app_id) {
        const app = apps.value.find((a) => a.id === frame.navigate_app_id)
        ElMessage.success(t('ai.navigating', { name: app?.name ?? `#${frame.navigate_app_id}` }))
        router.push('/apps')
      }
      scrollBottom()
      void loadConversations()
      ws?.close()
    } else if (frame.type === 'error') {
      ElMessage.error(frame.error)
      streaming.value = false
      ws?.close()
    }
  }
  ws.onerror = () => {
    streaming.value = false
    ElMessage.error(t('ai.wsError'))
  }
  ws.onopen = () => ws?.send(JSON.stringify({ conversation_id: activeId.value, content }))
}

function stopStreaming() {
  streaming.value = false
  if (streamText.value) {
    messages.value.push({
      id: Date.now(),
      role: 'assistant',
      content: streamText.value,
      created_at: new Date().toISOString(),
    })
    streamText.value = ''
  }
  ws?.close()
  ws = null
}

function scrollBottom() {
  void nextTick(() => {
    const box = document.querySelector('.ai-messages')
    if (box) box.scrollTop = box.scrollHeight
  })
}

function authToken(): string {
  return localStorage.getItem('portal.token') || ''
}

// ---------- Provider 设置 ----------
const providerDialog = ref(false)
const providers = ref<AiProvider[]>([])
const provDialog = ref(false)
const provEditing = ref<AiProvider | null>(null)
const provForm = reactive({ name: '', base_url: '', api_key: '', model: '' })
const models = ref<string[]>([])
const contextRounds = ref(6)
const contextAware = ref(false)

async function openSettings() {
  providers.value = await aiApi.providers()
  providerDialog.value = true
  const map = (await settingsApi.getSettings()) as Record<string, unknown>
  contextRounds.value = (map['ai.context_rounds'] as number) || 6
  contextAware.value = map['ai.context_aware'] === true
}

async function saveAiParams() {
  await settingsApi.updateSettings({
    'ai.context_rounds': contextRounds.value,
    'ai.context_aware': contextAware.value,
  } as unknown as Record<string, unknown>)
  ElMessage.success(t('settings.generalSaved'))
}

function openProvCreate() {
  provEditing.value = null
  Object.assign(provForm, { name: '', base_url: '', api_key: '', model: '' })
  provDialog.value = true
}

function openProvEdit(p: AiProvider) {
  provEditing.value = p
  Object.assign(provForm, { name: p.name, base_url: p.base_url, api_key: p.api_key, model: p.model })
}

async function testProvider() {
  try {
    const r = await aiApi.testProvider(provForm.base_url, provForm.api_key)
    if (r.ok) {
      models.value = r.models ?? []
      ElMessage.success(t('ai.prov.testOk'))
    } else {
      ElMessage.error(r.error || t('ai.prov.testFail'))
    }
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function saveProvider() {
  try {
    if (provEditing.value) await aiApi.updateProvider(provEditing.value.id, { ...provForm, enabled: true })
    else await aiApi.createProvider({ ...provForm, enabled: true })
    ElMessage.success(t('ai.prov.saved'))
    provDialog.value = false
    providers.value = await aiApi.providers()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function removeProvider(p: AiProvider) {
  await aiApi.deleteProvider(p.id)
  providers.value = await aiApi.providers()
}

// ---------- 应用草稿（M05-13） ----------
const draftDialog = ref(false)
const draftDesc = ref('')
const draft = ref<Record<string, unknown> | null>(null)

async function genDraft() {
  try {
    draft.value = await aiApi.generateAppDraft(draftDesc.value)
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function saveDraft() {
  if (!draft.value) return
  try {
    await portalApi.createApp({
      name: draft.value.name as string,
      description: draft.value.description as string,
      health_type: draft.value.health_type as string,
      health_target: (draft.value.health_target as string) || undefined,
      visibility: 'all',
      open_mode: 'newtab',
      urls: [],
    } as unknown as Parameters<typeof portalApi.createApp>[0])
    ElMessage.success(t('ai.draft.saved'))
    draftDialog.value = false
    draft.value = null
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

onMounted(async () => {
  await loadConversations()
  apps.value = await portalApi.listApps().catch(() => [] as PortalApp[])
})
</script>

<template>
  <div class="ai-page fade-up">
    <!-- 会话列表 -->
    <aside class="glass ai-side">
      <el-button type="primary" class="btn-gradient" size="small" :icon="Plus" style="width: 100%" @click="newConversation">
        {{ t('ai.newConversation') }}
      </el-button>
      <div class="conv-list">
        <div
          v-for="c in conversations"
          :key="c.id"
          class="conv-item"
          :class="{ active: c.id === activeId }"
          @click="openConversation(c.id)"
        >
          <span class="conv-title">{{ c.title }}</span>
          <span class="conv-ops">
            <el-button link size="small" :icon="Edit" @click.stop="renameConversation(c)" />
            <el-button link size="small" :icon="Delete" @click.stop="removeConversation(c)" />
          </span>
        </div>
      </div>
      <el-divider style="margin: 8px 0" />
      <el-button size="small" :icon="Setting" style="width: 100%" @click="openSettings">
        {{ t('ai.providerSettings') }}
      </el-button>
    </aside>

    <!-- 对话主区 -->
    <section class="glass ai-main">
      <div class="ai-messages">
        <div v-if="!messages.length && !streamText" class="ai-empty">
          <p>{{ t('ai.welcome') }}</p>
          <div class="quick-row">
            <el-button v-for="q in QUICK_PROMPTS" :key="q" size="small" round @click="sendQuick(q)">{{ q }}</el-button>
          </div>
        </div>
        <div v-for="m in messages" :key="m.id" class="msg" :class="m.role">
          <div class="bubble" v-html="renderMd(m.content)" />
        </div>
        <div v-if="streamText" class="msg assistant">
          <div class="bubble streaming" v-html="renderMd(streamText)" />
        </div>
      </div>

      <div class="ai-input-row">
        <el-input
          v-model="input"
          type="textarea"
          :rows="2"
          :placeholder="t('ai.inputPh')"
          @keydown.enter.exact.prevent="send"
        />
        <div class="ai-send-ops">
          <el-button size="small" @click="draftDialog = true">{{ t('ai.draft.entry') }}</el-button>
          <el-button v-if="streaming" size="small" type="danger" @click="stopStreaming">{{ t('ai.stop') }}</el-button>
          <el-button v-else type="primary" class="btn-gradient" @click="send">{{ t('ai.send') }}</el-button>
        </div>
      </div>
    </section>

    <!-- Provider 设置对话框 -->
    <el-dialog append-to-body v-model="providerDialog" :title="t('ai.providerSettings')" width="620px">
      <div class="prov-params">
        <span>{{ t('ai.contextRounds') }}</span>
        <el-input-number v-model="contextRounds" :min="0" :max="20" size="small" />
        <el-checkbox v-model="contextAware">{{ t('ai.contextAware') }}</el-checkbox>
        <el-button size="small" @click="saveAiParams">{{ t('common.save') }}</el-button>
      </div>
      <header class="prov-head">
        <h4>{{ t('ai.providers') }}</h4>
        <el-button size="small" type="primary" @click="openProvCreate">{{ t('common.add') }}</el-button>
      </header>
      <div v-if="!providers.length" class="muted">{{ t('ai.noProviders') }}</div>
      <div v-for="p in providers" :key="p.id" class="prov-row">
        <span class="prov-name">{{ p.name }}</span>
        <span class="prov-url">{{ p.base_url }} · {{ p.model }}</span>
        <el-button link size="small" @click="openProvEdit(p)">{{ t('common.edit') }}</el-button>
        <el-button link size="small" type="danger" :icon="Delete" @click="removeProvider(p)" />
      </div>

      <el-dialog v-model="provDialog" :title="provEditing ? t('ai.prov.edit') : t('ai.prov.add')" width="460px" append-to-body>
        <el-form label-width="90px">
          <el-form-item :label="t('ai.prov.name')"><el-input v-model="provForm.name" /></el-form-item>
          <el-form-item :label="t('ai.prov.baseUrl')">
            <el-input v-model="provForm.base_url" placeholder="https://api.deepseek.com/v1 或 http://nas:11434/v1" />
          </el-form-item>
          <el-form-item :label="t('ai.prov.key')">
            <el-input v-model="provForm.api_key" type="password" show-password />
          </el-form-item>
          <el-form-item :label="t('ai.prov.model')">
            <el-input v-model="provForm.model" style="flex: 1" />
            <el-button size="small" @click="testProvider">{{ t('ai.prov.testModels') }}</el-button>
          </el-form-item>
          <el-form-item v-if="models.length" :label="t('ai.prov.pickModel')">
            <el-select v-model="provForm.model" style="width: 100%">
              <el-option v-for="m in models" :key="m" :label="m" :value="m" />
            </el-select>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="provDialog = false">{{ t('common.cancel') }}</el-button>
          <el-button type="primary" class="btn-gradient" @click="saveProvider">{{ t('common.save') }}</el-button>
        </template>
      </el-dialog>
    </el-dialog>

    <!-- 应用草稿 -->
    <el-dialog append-to-body v-model="draftDialog" :title="t('ai.draft.title')" width="520px">
      <p class="muted">{{ t('ai.draft.hint') }}</p>
      <el-input v-model="draftDesc" type="textarea" :rows="4" :placeholder="t('ai.draft.ph')" />
      <div v-if="draft" class="draft-box">
        <div class="kv mono">{{ draft.name }} · {{ draft.description }}</div>
        <div class="kv mono">{{ t('ai.draft.probe') }}: {{ draft.health_type }} {{ draft.health_target }}</div>
        <div class="kv mono">{{ t('settings.tagInputPh') }}: {{ (draft.tags as string[]).join(', ') }}</div>
      </div>
      <template #footer>
        <el-button @click="draftDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button v-if="!draft" type="primary" class="btn-gradient" @click="genDraft">{{ t('ai.draft.generate') }}</el-button>
        <el-button v-else type="primary" class="btn-gradient" @click="saveDraft">{{ t('ai.draft.saveApp') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.ai-page {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 14px;
}
.ai-side {
  width: 230px;
  flex-shrink: 0;
  padding: 12px 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
}
.conv-list {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow-y: auto;
}
.conv-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 10px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
}
.conv-item.active,
.conv-item:hover {
  background: rgba(127, 127, 127, 0.14);
}
.conv-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ai-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  padding: 14px;
  gap: 10px;
}
.ai-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ai-empty {
  text-align: center;
  color: var(--p-muted);
  padding: 40px 0;
}
.quick-row {
  display: flex;
  gap: 8px;
  justify-content: center;
  flex-wrap: wrap;
  margin-top: 12px;
}
.msg {
  display: flex;
}
.msg.user {
  justify-content: flex-end;
}
.bubble {
  max-width: 76%;
  padding: 9px 13px;
  border-radius: 12px;
  font-size: 13.5px;
  line-height: 1.6;
  background: rgba(127, 127, 127, 0.12);
  word-break: break-word;
}
.msg.user .bubble {
  background: var(--el-color-primary);
  color: #fff;
}
.bubble :deep(pre) {
  background: rgba(0, 0, 0, 0.25);
  padding: 8px 10px;
  border-radius: 8px;
  overflow-x: auto;
  font-size: 12px;
}
.bubble :deep(code) {
  font-family: ui-monospace, monospace;
}
.bubble :deep(table) {
  border-collapse: collapse;
}
.bubble :deep(th),
.bubble :deep(td) {
  border: 1px solid rgba(127, 127, 127, 0.4);
  padding: 3px 8px;
}
.bubble.streaming::after {
  content: "▍";
  animation: blink 1s infinite;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}
.ai-input-row {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}
.ai-send-ops {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.prov-params {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  font-size: 13px;
}
.prov-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 8px 0;
}
.prov-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  border-radius: 8px;
  background: rgba(127, 127, 127, 0.08);
  font-size: 12.5px;
  margin-bottom: 6px;
}
.prov-name {
  font-weight: 700;
}
.prov-url {
  flex: 1;
  min-width: 0;
  color: var(--p-muted);
}
.muted {
  color: var(--p-muted);
  font-size: 12.5px;
}
.draft-box {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 10px;
}
.kv {
  padding: 6px 8px;
  background: rgba(127, 127, 127, 0.08);
  border-radius: 6px;
  font-size: 12.5px;
}
</style>
