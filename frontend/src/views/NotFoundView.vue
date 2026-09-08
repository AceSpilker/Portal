<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AuroraBackground from '../components/AuroraBackground.vue'

// 404 兜底页（路由 catch-all）：独立整页，不套 AppLayout，未登录访问同样成立
const { t } = useI18n()
const router = useRouter()
</script>

<template>
  <div class="notfound-view">
    <AuroraBackground />
    <div class="page">
      <div class="card glass fade-up">
        <p class="code">404</p>
        <h1 class="title">{{ t('notFound.title') }}</h1>
        <p class="muted desc">{{ t('notFound.desc') }}</p>
        <div class="actions">
          <el-button type="primary" size="large" class="btn-gradient" @click="router.push('/')">
            {{ t('notFound.backHome') }}
          </el-button>
          <el-button size="large" @click="router.back()">
            {{ t('notFound.back') }}
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page {
  min-height: 100vh;
  min-height: 100dvh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: clamp(16px, 4vw, 24px);
}
.card {
  width: min(460px, 100%);
  padding: clamp(28px, 5vw, 44px) clamp(24px, 5vw, 40px);
  text-align: center;
}
.code {
  margin: 0;
  font-size: clamp(56px, 12vw, 76px);
  font-weight: 700;
  line-height: 1;
  letter-spacing: 4px;
  background: linear-gradient(135deg, var(--p-primary, #4f6ef7), var(--p-primary-dark, #2c3fb3));
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.title {
  margin: 10px 0 6px;
  font-size: 22px;
  letter-spacing: 0.5px;
}
.desc {
  margin: 0 0 22px;
  font-size: 13.5px;
  color: var(--p-muted);
}
.actions {
  display: flex;
  justify-content: center;
  gap: 10px;
}
</style>
