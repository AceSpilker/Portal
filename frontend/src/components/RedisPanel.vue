<script setup lang="ts">
/**
 * Redis 面板（P25/M15-14）：连接配置（密码密文存储）+ 连接测试 +
 * 当前存储模式（redis/memory/redis-degraded）展示。
 */
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Refresh as IconRefresh } from '@element-plus/icons-vue'
import { redisApi } from '../api/redis'
import type { RedisStatus } from '../api/redis'

const { t } = useI18n()

const form = reactive({
  host: '',
  port: 6379,
  password: '',
  db: 0,
  key_prefix: 'portal:',
  enabled: false,
})
const passwordSet = ref(false)
const saving = ref(false)
const testing = ref(false)
const status = ref<RedisStatus | null>(null)

async function load() {
  try {
    const cfg = await redisApi.getConfig()
    Object.assign(form, {
      host: cfg.host,
      port: cfg.port,
      db: cfg.db,
      key_prefix: cfg.key_prefix,
      enabled: cfg.enabled,
      password: '',
    })
    passwordSet.value = cfg.password_set
    await loadStatus()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function loadStatus() {
  try {
    status.value = await redisApi.status()
  } catch {
    /* ignore */
  }
}

async function save() {
  saving.value = true
  try {
    const payload: Record<string, unknown> = { ...form }
    if (!form.password) delete payload.password
    await redisApi.saveConfig(payload)
    ElMessage.success(t('redis.saved'))
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    saving.value = false
  }
}

async function testConnection() {
  testing.value = true
  try {
    // 先保存再测（与后端"按已存配置测试"口径一致）
    const payload: Record<string, unknown> = { ...form }
    if (!form.password) delete payload.password
    await redisApi.saveConfig(payload)
    const r = await redisApi.test({})
    if (r.ok) {
      ElMessage.success(t('redis.testOk', { ver: r.server_version ?? '' }))
    } else {
      ElMessage.error(t('redis.testFail', { msg: r.error ?? '' }))
    }
    await loadStatus()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    testing.value = false
  }
}

const MODE_TAG: Record<string, 'success' | 'info' | 'warning'> = {
  redis: 'success',
  memory: 'info',
  'redis-degraded': 'warning',
}

onMounted(load)
</script>

<template>
  <div class="redis-panel">
    <section class="glass redis-card">
      <h3>{{ t('redis.configTitle') }}</h3>
      <p class="desc">{{ t('redis.configDesc') }}</p>
      <el-form label-position="top">
        <div class="grid">
          <el-form-item :label="t('redis.host')">
            <el-input v-model="form.host" placeholder="127.0.0.1" />
          </el-form-item>
          <el-form-item :label="t('redis.port')">
            <el-input-number v-model="form.port" :min="1" :max="65535" style="width: 100%" />
          </el-form-item>
          <el-form-item :label="t('redis.password')">
            <el-input
              v-model="form.password"
              type="password"
              show-password
              :placeholder="passwordSet ? t('redis.passwordKeep') : ''"
            />
          </el-form-item>
          <el-form-item label="DB">
            <el-input-number v-model="form.db" :min="0" :max="15" style="width: 100%" />
          </el-form-item>
          <el-form-item :label="t('redis.prefix')">
            <el-input v-model="form.key_prefix" maxlength="32" />
          </el-form-item>
          <el-form-item :label="t('redis.enabled')">
            <el-switch v-model="form.enabled" />
          </el-form-item>
        </div>
      </el-form>
      <div class="row-gap">
        <el-button type="primary" class="btn-gradient" :loading="saving" @click="save">{{ t('common.save') }}</el-button>
        <el-button :loading="testing" @click="testConnection">{{ t('redis.test') }}</el-button>
      </div>
    </section>

    <section class="glass redis-card">
      <header class="card-head">
        <h3>{{ t('redis.statusTitle') }}</h3>
        <el-button size="small" :icon="IconRefresh" circle @click="loadStatus" />
      </header>
      <p v-if="status" class="status-line">
        <span class="muted-tip">{{ t('redis.mode') }}</span>
        <el-tag :type="MODE_TAG[status.mode] ?? 'info'">{{ t(`redis.st.${status.mode}`) }}</el-tag>
        <el-tag v-if="status.connected" type="success" size="small">{{ t('redis.connected') }}</el-tag>
      </p>
      <p v-if="status?.last_error" class="err-line">{{ status.last_error }}</p>
      <p class="desc">{{ t('redis.statusDesc') }}</p>
    </section>
  </div>
</template>

<style scoped>
.redis-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.redis-card {
  padding: 14px 18px;
}
.redis-card h3 {
  margin: 0 0 4px;
  font-size: 14px;
}
.desc {
  margin: 0 0 10px;
  font-size: 12.5px;
  color: var(--p-muted);
}
.grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0 14px;
}
.row-gap {
  display: flex;
  gap: 8px;
  align-items: center;
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
.status-line {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 4px 0;
}
.err-line {
  color: var(--el-color-danger);
  font-size: 12px;
  word-break: break-all;
}
.muted-tip {
  font-size: 12.5px;
  color: var(--p-muted);
}
@media (max-width: 1000px) {
  .grid {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
