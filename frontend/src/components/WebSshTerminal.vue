<script setup lang="ts">
/**
 * Web SSH 终端（M17-17；dev-plan P21.2）：xterm.js + WebSocket 直连 NAS Shell。
 * 后端开关 security.webssh_enabled；连接/断开写审计（P20 凭据库选目标）。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { tunnelsApi, type SSHCredential } from '../api/tunnels'

const { t } = useI18n()

const visible = defineModel<boolean>({ required: true })
const creds = ref<SSHCredential[]>([])
const credId = ref<number | null>(null)
const connected = ref(false)
const termHost = ref<HTMLElement | null>(null)
let xterm: import('@xterm/xterm').Terminal | null = null
let ws: WebSocket | null = null
let fit: import('@xterm/addon-fit').FitAddon | null = null

async function loadCreds() {
  try {
    creds.value = await tunnelsApi.listCredentials()
    if (creds.value.length) credId.value = creds.value[0]!.id
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function connect() {
  if (!credId.value) {
    ElMessage.warning(t('webssh.needCred'))
    return
  }
  const { Terminal } = await import('@xterm/xterm')
  const { FitAddon } = await import('@xterm/addon-fit')
  if (!termHost.value) return
  termHost.value.innerHTML = ''
  xterm = new Terminal({ cursorBlink: true, fontSize: 13, convertEol: false })
  fit = new FitAddon()
  xterm.loadAddon(fit)
  xterm.open(termHost.value)
  fit.fit()

  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const token = localStorage.getItem('portal.token') ?? ''
  ws = new WebSocket(
    `${proto}://${location.host}/ws/ssh-terminal?token=${encodeURIComponent(token)}&cred=${credId.value}`,
  )
  ws.onopen = () => {
    connected.value = true
    xterm?.writeln(`\r\n${t('webssh.connected')}\r\n`)
  }
  ws.onmessage = (ev) => xterm?.write(ev.data)
  ws.onclose = () => {
    connected.value = false
    xterm?.writeln(`\r\n${t('webssh.closed')}\r\n`)
  }
  ws.onerror = () => {
    connected.value = false
    xterm?.writeln(`\r\n${t('webssh.error')}\r\n`)
  }
  xterm.onData((data) => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(data)
  })
}

function disconnect() {
  ws?.close()
  connected.value = false
}

onMounted(loadCreds)
onBeforeUnmount(() => {
  disconnect()
  xterm?.dispose()
  xterm = null
})

</script>

<template>
  <el-dialog v-model="visible" :title="t('webssh.title')" width="760px" append-to-body @open="loadCreds" @close="disconnect">
    <div class="webssh-bar">
      <el-select v-model="credId" style="width: 220px" :disabled="connected">
        <el-option v-for="c in creds" :key="c.id" :value="c.id" :label="`${c.name}（${c.username}@${c.host}）`" />
      </el-select>
      <el-button type="primary" class="btn-gradient" :disabled="connected || !credId" @click="connect">
        {{ t('webssh.connect') }}
      </el-button>
      <el-button v-if="connected" @click="disconnect">{{ t('webssh.disconnect') }}</el-button>
    </div>
    <div ref="termHost" class="term-host" />
    <p class="muted" style="margin-top: 8px">{{ t('webssh.tip') }}</p>
  </el-dialog>
</template>

<style scoped>
.webssh-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}
.term-host {
  width: 100%;
  height: 380px;
  background: #0b1020;
  border-radius: 10px;
  padding: 6px;
}
</style>
