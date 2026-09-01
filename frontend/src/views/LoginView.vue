<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getHealth } from '../api/health'

const checking = ref(false)
const apiStatus = ref<'' | 'ok' | 'fail'>('')

/** P0.5 联调自检：探测后端 /api/health。 */
async function checkBackend() {
  checking.value = true
  try {
    const info = await getHealth()
    apiStatus.value = 'ok'
    ElMessage.success(`后端连接成功：${info.app} v${info.version}`)
  } catch (e) {
    apiStatus.value = 'fail'
    ElMessage.error('后端连接失败，请确认 uvicorn 已启动（端口 8000）')
  } finally {
    checking.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <template #header>
        <div class="title">
          <h2>Portal</h2>
          <p>NAS 门户系统 · 登录</p>
        </div>
      </template>
      <el-alert type="info" :closable="false" show-icon title="登录功能在 P1 阶段实现（认证与账户）" />
      <el-form label-position="top" disabled style="margin-top: 16px">
        <el-form-item label="用户名">
          <el-input placeholder="admin" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input type="password" placeholder="••••••••" />
        </el-form-item>
        <el-button type="primary" style="width: 100%" disabled>登 录</el-button>
      </el-form>
      <el-divider />
      <el-button :loading="checking" style="width: 100%" @click="checkBackend">
        后端连接自检（/api/health）
      </el-button>
      <p v-if="apiStatus === 'ok'" class="hint ok">✅ 后端连通</p>
      <p v-else-if="apiStatus === 'fail'" class="hint fail">❌ 后端不可达</p>
    </el-card>
  </div>
</template>

<style scoped>
.login-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0b1c48 0%, #1e3a8a 60%, #4f6ef7 140%);
}
.login-card {
  width: 380px;
}
.title h2 {
  margin: 0;
  letter-spacing: 1px;
}
.title p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 13px;
}
.hint {
  text-align: center;
  font-size: 13px;
  margin: 8px 0 0;
}
.ok {
  color: #047857;
}
.fail {
  color: #b91c1c;
}
</style>
