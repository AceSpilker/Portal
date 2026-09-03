<script setup lang="ts">
import { onMounted, ref } from 'vue'
import QRCode from 'qrcode'
import { toolsApi } from '../api/tools'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import {
  base64Decode,
  base64Encode,
  dateToUnix,
  generatePassword,
  unixToDate,
  urlDecode,
  urlEncode,
} from '../utils/tools'

const { t } = useI18n()

// ---- 编解码 ----
type CodecMode = 'base64' | 'url'
const codecMode = ref<CodecMode>('base64')
const codecAction = ref<'encode' | 'decode'>('encode')
const codecInput = ref('')
const codecOutput = ref('')
const codecError = ref('')

function runCodec() {
  codecError.value = ''
  codecOutput.value = ''
  try {
    const text = codecInput.value
    if (codecMode.value === 'base64') {
      codecOutput.value = codecAction.value === 'encode' ? base64Encode(text) : base64Decode(text)
    } else {
      codecOutput.value = codecAction.value === 'encode' ? urlEncode(text) : urlDecode(text)
    }
  } catch (e) {
    codecError.value = (e as Error).message || t('tools.codecFail')
  }
}

async function copyOutput() {
  if (!codecOutput.value) return
  await navigator.clipboard.writeText(codecOutput.value)
  ElMessage.success(t('tools.copied'))
}

// ---- 时间戳 ----
const tsInput = ref(String(Math.floor(Date.now() / 1000)))
const tsOutput = ref(unixToDate(tsInput.value))
const dateInput = ref('')
const dateOutput = ref('')

function tsToDate() {
  tsOutput.value = unixToDate(tsInput.value)
}

function dateToTs() {
  dateOutput.value = dateToUnix(dateInput.value)
}

function useNow() {
  dateInput.value = formatNow()
  dateToTs()
}

function formatNow(): string {
  const d = new Date()
  const p2 = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}T${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}`
}

// ---- 密码生成 ----
const pwdLength = ref(16)
const pwdOpts = ref({ upper: true, lower: true, digits: true, symbols: true })
const pwdOutput = ref('')

function genPassword() {
  pwdOutput.value = generatePassword({ length: pwdLength.value, ...pwdOpts.value })
  if (!pwdOutput.value) ElMessage.warning(t('tools.pwdNeedOptions'))
}

// ---- 网络唤醒 WoL（M10-1）----
const wolMac = ref('')
const wolSending = ref(false)
const wolTargets = ref<{ id: number; name: string; mac: string; note: string }[]>([])

async function loadWolTargets() {
  try {
    wolTargets.value = await toolsApi.wolTargets.list()
  } catch {
    wolTargets.value = []
  }
}

async function sendWol(mac?: string, name?: string) {
  const target = mac ?? wolMac.value
  if (!target) return
  wolSending.value = true
  try {
    await toolsApi.wol(target)
    ElMessage.success(t('tools.wolSent', { name: name || target }))
    wolMac.value = ''
    await loadWolTargets()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    wolSending.value = false
  }
}

// ---- Ping / 端口测试（M10-3）----
const pingHost = ref('')
const pingPort = ref(80)
const pingResult = ref<{ ok: boolean; latency_ms: number | null } | null>(null)
const pingLoading = ref(false)

async function runPortCheck() {
  pingLoading.value = true
  pingResult.value = null
  try {
    pingResult.value = await toolsApi.portCheck(pingHost.value, pingPort.value)
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    pingLoading.value = false
  }
}

// ---- 二维码生成（M10-5）----
const qrText = ref('')
const qrDataUrl = ref('')

async function genQr() {
  if (!qrText.value) {
    qrDataUrl.value = ''
    return
  }
  qrDataUrl.value = await QRCode.toDataURL(qrText.value, { width: 220, margin: 1 })
}

function downloadQr() {
  if (!qrDataUrl.value) return
  const a = document.createElement('a')
  a.href = qrDataUrl.value
  a.download = 'qrcode.png'
  a.click()
}

const copyText = async (text: string) => {
  if (!text) return
  await navigator.clipboard.writeText(text)
  ElMessage.success(t('tools.copied'))
}
onMounted(loadWolTargets)
</script>

<template>
  <div class="tools-page">
    <section class="tool glass">
      <h3>{{ t('tools.codecTitle') }}</h3>
      <el-radio-group v-model="codecMode" size="small">
        <el-radio-button value="base64">Base64</el-radio-button>
        <el-radio-button value="url">URL</el-radio-button>
      </el-radio-group>
      <el-radio-group v-model="codecAction" size="small">
        <el-radio-button value="encode">{{ t('tools.encode') }}</el-radio-button>
        <el-radio-button value="decode">{{ t('tools.decode') }}</el-radio-button>
      </el-radio-group>
      <el-input
        v-model="codecInput"
        type="textarea"
        :rows="3"
        :placeholder="t('tools.codecInputPh')"
      />
      <el-button type="primary" class="btn-gradient" @click="runCodec">
        {{ codecAction === 'encode' ? t('tools.encode') : t('tools.decode') }}
      </el-button>
      <div v-if="codecOutput" class="tool-output">
        <span class="tool-output-text">{{ codecOutput }}</span>
        <el-button link type="primary" @click="copyOutput">{{ t('tools.copy') }}</el-button>
      </div>
      <p v-if="codecError" class="tool-error">{{ codecError }}</p>
    </section>

    <section class="tool glass">
      <h3>{{ t('tools.tsTitle') }}</h3>
      <div class="tool-row">
        <el-input v-model="tsInput" :placeholder="t('tools.tsPh')" />
        <el-button @click="tsToDate">{{ t('tools.tsToDate') }}</el-button>
      </div>
      <div class="tool-result">{{ tsOutput || '—' }}</div>
      <el-divider />
      <div class="tool-row">
        <el-input v-model="dateInput" type="datetime-local" />
        <el-button @click="dateToTs">{{ t('tools.dateToTs') }}</el-button>
        <el-button @click="useNow">{{ t('tools.now') }}</el-button>
      </div>
      <div class="tool-result">{{ dateOutput || '—' }}</div>
    </section>

    <section class="tool glass">
      <h3>{{ t('tools.pwdTitle') }}</h3>
      <div class="tool-row">
        <span class="muted">{{ t('tools.pwdLength') }}：{{ pwdLength }}</span>
        <el-slider v-model="pwdLength" :min="6" :max="64" style="flex: 1" />
      </div>
      <div class="pwd-opts">
        <el-checkbox v-model="pwdOpts.upper">{{ t('tools.pwdUpper') }}</el-checkbox>
        <el-checkbox v-model="pwdOpts.lower">{{ t('tools.pwdLower') }}</el-checkbox>
        <el-checkbox v-model="pwdOpts.digits">{{ t('tools.pwdDigits') }}</el-checkbox>
        <el-checkbox v-model="pwdOpts.symbols">{{ t('tools.pwdSymbols') }}</el-checkbox>
      </div>
      <el-button type="primary" class="btn-gradient" @click="genPassword">
        {{ t('tools.pwdGenerate') }}
      </el-button>
      <div v-if="pwdOutput" class="tool-output">
        <span class="tool-output-text pwd">{{ pwdOutput }}</span>
        <el-button link type="primary" @click="copyText(pwdOutput)">{{ t('tools.copy') }}</el-button>
      </div>
    </section>
    <!-- 网络唤醒（M10-1） -->
    <section class="tool glass">
      <h3>{{ t('tools.wolTitle') }}</h3>
      <div class="tool-row">
        <el-input
          v-model="wolMac"
          :placeholder="t('tools.wolPh')"
          style="flex: 1"
          clearable
        />
        <el-button type="primary" class="btn-gradient" :loading="wolSending" @click="sendWol()">
          {{ t('tools.wolSend') }}
        </el-button>
      </div>
      <div v-if="wolTargets.length" class="wol-targets">
        <div v-for="tg in wolTargets" :key="tg.id" class="wol-row">
          <span class="wol-name">{{ tg.name }}</span>
          <code class="wol-mac">{{ tg.mac }}</code>
          <el-button link size="small" type="primary" @click="sendWol(tg.mac, tg.name)">
            {{ t('tools.wolSend') }}
          </el-button>
          <el-button
            link
            size="small"
            type="danger"
            @click="async () => { await toolsApi.wolTargets.remove(tg.id); await loadWolTargets() }"
          >✕</el-button>
        </div>
      </div>
    </section>

    <!-- Ping / 端口测试（M10-3） -->
    <section class="tool glass">
      <h3>{{ t('tools.pingTitle') }}</h3>
      <div class="tool-row">
        <el-input v-model="pingHost" :placeholder="t('tools.pingHostPh')" style="flex: 1" />
        <el-input-number v-model="pingPort" :min="1" :max="65535" style="width: 130px" />
        <el-button type="primary" :loading="pingLoading" @click="runPortCheck">
          {{ t('tools.pingRun') }}
        </el-button>
      </div>
      <div v-if="pingResult" class="tool-output">
        <span :class="pingResult.ok ? 'ping-ok' : 'ping-fail'">
          {{ pingResult.ok ? t('tools.pingOk', { ms: pingResult.latency_ms }) : t('tools.pingFail') }}
        </span>
      </div>
    </section>

    <!-- 二维码生成（M10-5） -->
    <section class="tool glass">
      <h3>{{ t('tools.qrTitle') }}</h3>
      <div class="tool-row">
        <el-input
          v-model="qrText"
          :placeholder="t('tools.qrPh')"
          style="flex: 1"
          @change="genQr"
        />
        <el-button type="primary" @click="genQr">{{ t('tools.qrGen') }}</el-button>
      </div>
      <div v-if="qrDataUrl" class="qr-box">
        <img :src="qrDataUrl" alt="QR" width="180" height="180" />
        <el-button link type="primary" @click="downloadQr">{{ t('tools.qrDownload') }}</el-button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.tools-page {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.tool {
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.wol-targets {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.wol-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 0;
}
.wol-name {
  font-weight: 600;
  font-size: 13px;
  min-width: 120px;
}
.wol-mac {
  font-size: 12px;
  color: var(--p-muted);
  flex: 1;
}
.ping-ok {
  color: var(--el-color-success, #22c55e);
  font-weight: 600;
}
.ping-fail {
  color: var(--el-color-danger, #ef4444);
  font-weight: 600;
}
.qr-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}
.qr-box img {
  border-radius: 8px;
  background: #fff;
  padding: 6px;
}
.tool h3 {
  margin: 0;
  font-size: 15px;
}
.tool-row {
  display: flex;
  gap: 10px;
  align-items: center;
}
.tool-output {
  display: flex;
  align-items: center;
  gap: 10px;
  background: color-mix(in srgb, var(--p-primary) 5%, transparent);
  border: 1px solid var(--p-card-border);
  border-radius: 8px;
  padding: 10px 12px;
}
.tool-output-text {
  flex: 1;
  word-break: break-all;
  font-size: 13px;
}
.tool-output-text.pwd {
  font-family: monospace;
  font-size: 15px;
  letter-spacing: 1px;
}
.tool-result {
  min-height: 32px;
  display: flex;
  align-items: center;
  background: color-mix(in srgb, var(--p-primary) 5%, transparent);
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 13px;
}
.pwd-opts {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
}
.muted {
  color: var(--p-muted);
  font-size: 13px;
  white-space: nowrap;
}
.tool-error {
  margin: 0;
  color: #ef4444;
  font-size: 12.5px;
}
</style>
