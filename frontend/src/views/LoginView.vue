<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User as IconUser, Lock as IconLock, MagicStick as IconWand } from '@element-plus/icons-vue'
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
const siteName = ref('Portal')

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
    ElMessage.success('初始化完成，欢迎使用的 Portal！')
    router.push('/')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '初始化失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <AuroraBackground />
  <div class="page">
    <!-- 品牌 -->
    <div class="brand fade-up">
      <span class="brand-text">Portal</span>
      <span class="brand-sub">NAS 门户系统</span>
    </div>

    <!-- 玻璃卡片 -->
    <div class="card glass fade-up" style="animation-delay: 0.12s">
      <div v-if="mode === 'loading'" class="center">
        <el-icon class="is-loading spin"><IconWand /></el-icon>
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
          class="stagger"
          title="后端服务不可达，请确认服务已启动"
          style="margin-bottom: 14px"
        />

        <!-- 登录表单 -->
        <el-form
          v-if="mode === 'login'"
          class="stagger"
          @submit.prevent="handleLogin"
        >
          <el-form-item>
            <el-input v-model="loginForm.username" size="large" placeholder="用户名" :prefix-icon="IconUser" @keyup.enter="handleLogin" />
          </el-form-item>
          <el-form-item>
            <el-input v-model="loginForm.password" size="large" type="password" show-password placeholder="密码" :prefix-icon="IconLock" @keyup.enter="handleLogin" />
          </el-form-item>
          <el-button
            class="btn-gradient submit"
            size="large"
            type="primary"
            :loading="submitting"
            :disabled="!backendUp"
            @click="handleLogin"
          >
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
            <el-input v-model="initForm.confirm" size="large" type="password" show-password placeholder="确认密码" :prefix-icon="IconLock" @keyup.enter="handleInit" />
          </el-form-item>
          <el-button class="btn-gradient submit" size="large" type="primary" :loading="submitting" @click="handleInit">
            创建管理员并进入
          </el-button>
        </el-form>

        <p class="foot muted">P1 认证与账户 · 已接入</p>
      </template>
    </div>

    <p class="copyright fade-up" style="animation-delay: 0.3s">Portal · 自托管 NAS 门户</p>
  </div>
</template>

<style scoped>
.page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 22px;
  padding: 24px;
}
.brand {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.brand-text {
  font-size: 34px;
}
.brand-sub {
  color: var(--p-muted);
  font-size: 14px;
  letter-spacing: 3px;
}
.card {
  width: min(420px, 92vw);
  padding: 34px 34px 22px;
}
.head h1 {
  margin: 0 0 4px;
  font-size: 24px;
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
.spin {
  font-size: 30px;
  color: var(--p-primary);
}
.muted {
  color: var(--p-muted);
}
.submit {
  width: 100%;
  margin-top: 6px;
  letter-spacing: 6px;
}
.foot {
  text-align: center;
  font-size: 12px;
  margin: 18px 0 0;
  opacity: 0.6;
}
.copyright {
  color: rgba(255, 255, 255, 0.28);
  font-size: 12px;
  letter-spacing: 1px;
}

/* ===== 移动端适配（M16）===== */
@media (max-width: 767px) {
  .page {
    padding: 20px 14px calc(24px + env(safe-area-inset-bottom));
    gap: 16px;
  }
  .card {
    padding: 26px 22px 18px;
  }
  .brand-text {
    font-size: 28px;
  }
}
</style>
