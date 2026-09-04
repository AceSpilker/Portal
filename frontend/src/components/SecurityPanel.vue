<script setup lang="ts">
/**
 * 安全面板（P17.1/P17.2；M01-7/8、M14-1/7）：
 * TOTP 两步验证（扫码启用/关闭）、会话设备管理（下线）、API Token 管理、恢复出厂。
 */
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete as IconDelete, Key as IconKey } from '@element-plus/icons-vue'
import QRCode from 'qrcode'
import { authApi } from '../api/auth'
import { settingsApi } from '../api/settings'

interface SessionRow {
  id: number
  device: string
  ip: string
  created_at: string | null
  last_seen_at: string | null
  revoked: boolean
}
interface TokenRow {
  id: number
  name: string
  prefix: string
  scope: string
  expires_at: string | null
  last_used_at: string | null
}

const { t } = useI18n()

// ---- TOTP ----
const totpEnabled = ref(false)
const totpSetup = ref<{ secret: string; otpauth_uri: string } | null>(null)
const qrUrl = ref('')
const totpCode = ref('')
const recoveryCodes = ref<string[]>([])
const recoveryShow = ref(false)

// ---- 会话 ----
const sessions = ref<SessionRow[]>([])

// ---- Token ----
const tokens = ref<TokenRow[]>([])
const tokenDlg = ref(false)
const tokenForm = reactive({ name: '', scope: 'ro', expires_at: '' })
const newTokenPlain = ref('')

async function loadAll() {
  try {
    const [s, sess, toks] = await Promise.all([authApi.me(), authApi.sessions(), settingsApi.getTokens()])
    totpEnabled.value = (s as unknown as { totp_enabled?: boolean }).totp_enabled === true
    sessions.value = sess
    tokens.value = toks
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function startTotp() {
  try {
    totpSetup.value = await authApi.totpSetup()
    qrUrl.value = await QRCode.toDataURL(totpSetup.value.otpauth_uri, { width: 180, margin: 1 })
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function confirmTotp() {
  try {
    const r = await authApi.totpEnable(totpCode.value.trim())
    recoveryCodes.value = r.recovery_codes
    totpEnabled.value = true
    totpSetup.value = null
    totpCode.value = ''
    recoveryShow.value = true
    ElMessage.success(t('security.totpEnabled'))
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function disableTotp() {
  try {
    const { value } = await ElMessageBox.prompt(t('security.totpDisablePrompt'), t('common.confirm'), {
      inputPlaceholder: '123456',
    })
    await authApi.totpDisable(value || '', '')
    totpEnabled.value = false
    ElMessage.success(t('security.totpDisabled'))
  } catch {
    /* 取消 */
  }
}

async function revokeSession(row: SessionRow) {
  try {
    await authApi.revokeSession(row.id)
    sessions.value = sessions.value.filter((x) => x.id !== row.id)
    ElMessage.success(t('security.sessionRevoked'))
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

function openTokenDlg() {
  tokenForm.name = ''
  tokenForm.scope = 'ro'
  tokenForm.expires_at = ''
  newTokenPlain.value = ''
  tokenDlg.value = true
}

async function createToken() {
  if (!tokenForm.name.trim()) {
    ElMessage.warning(t('security.tokenNameRequired'))
    return
  }
  try {
    const r = await settingsApi.createToken({
      name: tokenForm.name.trim(),
      scope: tokenForm.scope,
      expires_at: tokenForm.expires_at || null,
    })
    newTokenPlain.value = r.token
    await loadTokensOnly()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function loadTokensOnly() {
  tokens.value = await settingsApi.getTokens()
}

async function revokeToken(row: TokenRow) {
  try {
    await settingsApi.revokeToken(row.id)
    tokens.value = tokens.value.filter((x) => x.id !== row.id)
    ElMessage.success(t('security.tokenRevoked'))
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function copyToken() {
  try {
    await navigator.clipboard.writeText(newTokenPlain.value)
    ElMessage.success(t('entry.copied'))
  } catch {
    /* ignore */
  }
}

// ---- 恢复出厂 ----
async function factoryReset() {
  const { value } = await ElMessageBox.prompt(
    t('security.resetPrompt'),
    t('security.resetTitle'),
    { inputType: 'password', inputPlaceholder: t('login.passwordPh'), type: 'warning' },
  ).catch(() => ({ value: null }))
  if (!value) return
  try {
    await settingsApi.factoryReset(value)
    ElMessage.success(t('security.resetDone'))
    setTimeout(() => window.location.reload(), 800)
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="sec-panel">
    <section class="glass sec-card">
      <h3>{{ t('security.totpTitle') }}</h3>
      <p class="desc">{{ t('security.totpDesc') }}</p>

      <template v-if="!totpEnabled && !totpSetup">
        <el-button type="primary" class="btn-gradient" :icon="IconKey" @click="startTotp">
          {{ t('security.totpStart') }}
        </el-button>
      </template>

      <template v-else-if="totpSetup">
        <div class="totp-setup">
          <img :src="qrUrl" alt="TOTP QR" class="totp-qr" />
          <div class="totp-secret mono">{{ totpSetup.secret }}</div>
          <el-input v-model="totpCode" :placeholder="t('security.totpCodePh')" style="max-width: 220px" />
          <div class="row-gap">
            <el-button type="primary" class="btn-gradient" @click="confirmTotp">{{ t('common.confirm') }}</el-button>
            <el-button @click="totpSetup = null">{{ t('common.cancel') }}</el-button>
          </div>
        </div>
      </template>

      <template v-else>
        <div class="row-gap">
          <el-tag type="success">{{ t('security.totpOn') }}</el-tag>
          <el-button size="small" @click="disableTotp">{{ t('security.totpTurnOff') }}</el-button>
        </div>
      </template>

      <el-dialog v-model="recoveryShow" :title="t('security.recoveryTitle')" width="420px" append-to-body>
        <p class="desc">{{ t('security.recoveryTip') }}</p>
        <div class="recovery-grid mono">
          <code v-for="c in recoveryCodes" :key="c">{{ c }}</code>
        </div>
      </el-dialog>
    </section>

    <section class="glass sec-card">
      <h3>{{ t('security.sessionsTitle') }}</h3>
      <el-table :data="sessions" size="small" style="width: 100%">
        <el-table-column prop="device" :label="t('security.colDevice')" min-width="220" show-overflow-tooltip />
        <el-table-column prop="ip" :label="t('security.colIp')" width="130" />
        <el-table-column :label="t('security.colLastSeen')" width="160">
          <template #default="{ row }">
            {{ (row.last_seen_at ?? row.created_at ?? '').replace('T', ' ').slice(0, 16) }}
          </template>
        </el-table-column>
        <el-table-column width="90" align="right">
          <template #default="{ row }">
            <el-button link size="small" type="danger" :icon="IconDelete" @click="revokeSession(row)">
              {{ t('security.kick') }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section class="glass sec-card">
      <header class="card-head">
        <h3>{{ t('security.tokensTitle') }}</h3>
        <el-button size="small" type="primary" class="btn-gradient" @click="openTokenDlg">
          {{ t('security.tokenCreate') }}
        </el-button>
      </header>
      <el-table :data="tokens" size="small" style="width: 100%">
        <el-table-column prop="name" :label="t('security.colName')" min-width="140" />
        <el-table-column prop="prefix" :label="t('security.colPrefix')" width="110">
          <template #default="{ row }"><code class="mono">{{ row.prefix }}…</code></template>
        </el-table-column>
        <el-table-column :label="t('security.colScope')" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.scope === 'rw' ? 'warning' : 'info'">{{ row.scope }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column width="90" align="right">
          <template #default="{ row }">
            <el-button link size="small" type="danger" @click="revokeToken(row)">{{ t('security.revoke') }}</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 创建 Token：明文仅展示一次 -->
      <el-dialog v-model="tokenDlg" :title="t('security.tokenCreate')" width="430px" append-to-body>
        <template v-if="!newTokenPlain">
          <el-form label-position="top">
            <el-form-item :label="t('security.colName')">
              <el-input v-model="tokenForm.name" maxlength="64" />
            </el-form-item>
            <el-form-item :label="t('security.colScope')">
              <el-radio-group v-model="tokenForm.scope">
                <el-radio value="ro">ro（{{ t('security.scopeRo') }}）</el-radio>
                <el-radio value="rw">rw（{{ t('security.scopeRw') }}）</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item :label="t('security.tokenExpires')">
              <el-date-picker v-model="tokenForm.expires_at" type="date" value-format="YYYY-MM-DD" clearable style="width: 100%" />
            </el-form-item>
          </el-form>
          <el-button type="primary" class="btn-gradient" @click="createToken">{{ t('security.tokenCreate') }}</el-button>
        </template>
        <template v-else>
          <p class="desc">{{ t('security.tokenOnce') }}</p>
          <code class="token-plain mono">{{ newTokenPlain }}</code>
          <div class="row-gap" style="margin-top: 10px">
            <el-button size="small" @click="copyToken">{{ t('tools.copy') }}</el-button>
            <el-button size="small" type="primary" @click="tokenDlg = false">{{ t('common.close') }}</el-button>
          </div>
        </template>
      </el-dialog>
    </section>

    <section class="glass sec-card danger-zone">
      <h3>{{ t('security.resetTitle') }}</h3>
      <p class="desc">{{ t('security.resetDesc') }}</p>
      <el-button type="danger" plain @click="factoryReset">{{ t('security.resetBtn') }}</el-button>
    </section>
  </div>
</template>


<style scoped>
.sec-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.sec-card {
  padding: 14px 18px;
}
.sec-card h3 {
  margin: 0 0 4px;
  font-size: 14px;
}
.desc {
  margin: 0 0 10px;
  font-size: 12.5px;
  color: var(--p-muted);
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.card-head h3 {
  margin: 0;
}
.totp-setup {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
}
.totp-qr {
  border-radius: 8px;
}
.mono {
  font-family: ui-monospace, monospace;
  font-size: 12px;
  word-break: break-all;
}
.row-gap {
  display: flex;
  gap: 8px;
  align-items: center;
}
.recovery-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
}
.recovery-grid code {
  background: color-mix(in srgb, var(--p-primary) 8%, transparent);
  border-radius: 6px;
  padding: 4px 8px;
}
.token-plain {
  display: block;
  padding: 8px 10px;
  background: color-mix(in srgb, var(--p-primary) 8%, transparent);
  border-radius: 8px;
  user-select: all;
}
.danger-zone {
  border: 1px solid color-mix(in srgb, var(--el-color-danger) 30%, transparent);
}
</style>
