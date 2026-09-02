<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User as IconUser, Lock as IconLock } from '@element-plus/icons-vue'
import AuroraBackground from '../components/AuroraBackground.vue'
import { useAuthStore } from '../stores/auth'
import { authApi } from '../api/auth'
import { getHealth } from '../api/health'

const router = useRouter()
const auth = useAuthStore()

type Mode = 'loading' | 'login' | 'init'
const mode = ref<Mode>('loading')
const backendUp = ref(true)
const submitting = ref(false)

const loginForm = reactive({ username: '', password: '' })
const initForm = reactive({ username: '', password: '', confirm: '', site_name: 'Portal' })

onMounted(async () => {
  try {
    const info = await getHealth()
    backendUp.value = true
    mode.value = info.initialized ? 'login' : 'init'
  } catch {
    backendUp.value = false
    mode.value = 'login'
  }
})

async function handleLogin() {
  if (submitting.value) return
  if (!loginForm.username || !loginForm.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  submitting.value = true
  try {
    const resp = await authApi.login({ ...loginForm })
    auth.setSession(resp.access_token, resp.refresh_token, resp.user)
    ElMessage.success(`欢迎回来，${resp.user.username}`)
    router.push('/')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '登录失败')
  } finally {
    submitting.value = false
  }
}

async function handleInit() {
  if (submitting.value) return
  if (!initForm.username || !initForm.password) {
    ElMessage.warning('请填写管理员账号与密码')
    return
  }
  if (initForm.password !== initForm.confirm) {
    ElMessage.warning('两次输入的密码不一致')
    return
  }
  submitting.value = true
  try {
    siteName.value = initForm.site_name || 'Portal'
    const resp = await authApi.init({ ...initForm })
    auth.setSession(resp.access_token, resp.refresh_token, resp.user)
    ElMessage.success('初始化完成，欢迎使用！')
    router.push('/')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '初始化失败')
  } finally {
    submitting.value = false
  }
}

const siteName = ref('Portal')
</script>

<template>
  <AuroraBackground />
  <div class="page">
    <!-- 品牌 -->
    <div class="brand fade-up">
      <span class="brand-text">Portal</span>
      <span class="brand-sub">NAS 门户系统</span>
    </div>

    <!-- 卡片 -->
    <div class="card glass fade-up" style="animation-delay: 0.12s">
      <div v-if="mode === 'loading'" class="center">
        <span class="spinner" />
        <p class="muted">正在连接服务器…</p>
      </div>

      <template v-else>
        <div class="head stagger">
          <h1>{{ mode === 'init' ? '初始化向导' : '欢迎回来' }}</h1>
          <p class="muted">
            {{ mode === 'init' ? '首次使用，创建管理员账号' : '登录以进入你的门户' }}
          </p>
        </div>

        <el-alert
          v-if="!backendUp"
          type="error"
          :closable="false"
          show-icon
          title="后端服务不可达，请确认服务已启动"
          style="margin-bottom: 14px"
        />

        <!-- 登录表单 -->
        <el-form v-if="mode === 'login'" class="stagger" @submit.prevent="handleLogin">
          <el-form-item>
            <el-input v-model="loginForm.username" size="large" placeholder="用户名" :prefix-icon="IconUser" autocomplete="username" />
          </el-form-item>
          <el-form-item>
            <el-input v-model="loginForm.password" size="large" type="password" show-password placeholder="密码" :prefix-icon="IconLock" autocomplete="current-password" />
          </el-form-item>
          <el-button class="btn-gradient submit" size="large" type="primary" :loading="submitting" :disabled="!backendUp" native-type="submit">
            登 录
          </el-button>
        </el-form>

        <!-- 初始化表单 -->
        <el-form v-else class="stagger" @submit.prevent="handleInit">
          <el-form-item>
            <el-input v-model="initForm.site_name" size="large" placeholder="站点名称（可修改）" />
          </el-form-item>
          <el-form-item>
            <el-input v-model="initForm.username" size="large" placeholder="管理员用户名" :prefix-icon="IconUser" />
          </el-form-item>
          <el-form-item>
            <el-input v-model="initForm.password" size="large" type="password" show-password placeholder="密码（≥8 位，含字母和数字）" :prefix-icon="IconLock" />
          </el-form-item>
          <el-form-item>
            <el-input v-model="initForm.confirm" size="large" type="password" show-password placeholder="确认密码" :prefix-icon="IconLock" />
          </el-form-item>
          <el-button class="btn-gradient submit" size="large" type="primary" native-type="submit" :loading="submitting">
            创建管理员并进入
          </el-button>
        </el-form>

        <p class="foot">加密传输已启用 · 数据安全传输</p>
      </template>
    </div>

    <p class="copyright fade-up" style="animation-delay: 0.3s">Portal · 自托管 NAS 门户</p>
  </div>
</template>

<style scoped>
.page {
  min-height: 100vh;
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: clamp(16px, 2.4vh, 22px);
  padding: clamp(16px, 4vw, 24px);
}
.brand {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.brand-text {
  font-size: clamp(30px, 6vw, 34px);
}
.brand-sub {
  color: var(--p-muted);
  font-size: 14px;
  letter-spacing: 3px;
}
.card {
  width: min(420px, 100%);
  padding: clamp(24px, 4.5vw, 34px) clamp(20px, 4.5vw, 34px) clamp(18px, 3vw, 24px);
}
.head h1 {
  margin: 0 0 4px;
  font-size: 24px;
  letter-spacing: 0.5px;
}
.head .muted {
  margin: 0 0 18px;
  font-size: 13.5px;
  color: var(--p-muted);
}
.center {
  text-align: center;
  padding: 30px 0;
}
.spinner {
  display: inline-block;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 3px solid rgba(91, 95, 241, 0.2);
  border-top-color: var(--p-primary);
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
.muted {
  color: var(--p-muted);
}
.submit {
  width: 100%;
  margin-top: 6px;
  letter-spacing: 6px;
  height: 44px;
  border-radius: 12px;
  font-size: 15px;
}
:deep(.el-input__wrapper) {
  padding: 4px 14px;
}
.foot {
  text-align: center;
  font-size: 12px;
  margin: 16px 0 0;
  color: var(--p-muted);
  opacity: 0.8;
}
.copyright {
  color: rgba(23, 33, 58, 0.35);
  font-size: 12px;
  letter-spacing: 1px;
}

/* ===== 移动端适配（M16）===== */
@media (max-width: 767px) {
  .page {
    padding: max(28px, env(safe-area-inset-top)) 16px calc(24px + env(safe-area-inset-bottom));
    gap: 18px;
    justify-content: flex-start;
    padding-top: 12vh;
  }
  .brand {
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }
  .brand-text {
    font-size: 40px;
  }
  .brand-sub {
    font-size: 12px;
    letter-spacing: 5px;
  }
  .card {
    padding: 26px 20px 20px;
    border-radius: 24px;
  }
  .head h1 {
    font-size: 21px;
    text-align: center;
  }
  .head .muted {
    text-align: center;
  }
  :deep(.el-form-item) {
    margin-bottom: 16px;
  }
  :deep(.el-input__wrapper) {
    padding: 4px 14px;
  }
  .submit {
    height: 48px;
    letter-spacing: 4px;
    font-size: 16px;
  }
  .foot {
    margin-top: 14px;
  }
}
</style>
