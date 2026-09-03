<script setup lang="ts">
/**
 * 访客首页（M01-10；dev-plan 7.5）：免登录只读门户。
 * 仅 visibility=public 应用；guest.enabled 关闭时提示未开启。
 */
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '../components/AppIcon.vue'

const { t } = useI18n()
const apps = ref<{ id: number; name: string; icon: string; icon_type: string }[]>([])
const disabled = ref(false)
const siteName = ref('Portal')

onMounted(async () => {
  try {
    const resp = await fetch('/api/public/apps')
    if (resp.status === 404) {
      disabled.value = true
      return
    }
    const body = await resp.json()
    // 响应经传输加密豁免（P 端点），直接 data
    apps.value = body.data ?? []
    siteName.value = 'Portal'
  } catch {
    disabled.value = true
  }
})
</script>

<template>
  <div class="guest">
    <div class="guest-head glass">
      <h1>{{ siteName }}</h1>
      <p>{{ t('guest.tagline') }}</p>
    </div>
    <section v-if="disabled" class="glass guest-empty">
      {{ t('guest.disabled') }}
    </section>
    <section v-else class="guest-grid glass">
      <div v-for="a in apps" :key="a.id" class="guest-tile">
        <AppIcon :icon="a.icon" :icon-type="a.icon_type" :size="34" />
        <span class="g-name">{{ a.name }}</span>
      </div>
      <p v-if="!apps.length" class="g-empty">{{ t('guest.noApps') }}</p>
    </section>
    <div class="guest-foot">
      <router-link to="/login">{{ t('guest.toLogin') }}</router-link>
    </div>
  </div>
</template>

<style scoped>
.guest {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  gap: 18px;
  max-width: 900px;
  margin: 0 auto;
  padding: 40px 20px;
  box-sizing: border-box;
}
.guest-head {
  text-align: center;
  border-radius: 16px;
  padding: 26px;
}
.guest-head h1 {
  margin: 0 0 6px;
  font-size: 26px;
}
.guest-head p {
  margin: 0;
  color: var(--p-muted);
  font-size: 13px;
}
.guest-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 14px;
  padding: 20px;
  border-radius: 16px;
}
.guest-tile {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 16px 8px;
  border: 1px solid var(--p-card-border);
  border-radius: 12px;
  background: var(--p-card);
}
.g-name {
  font-size: 13px;
  font-weight: 600;
}
.g-empty {
  margin: 0;
  color: var(--p-muted);
}
.guest-empty {
  padding: 30px;
  border-radius: 16px;
  text-align: center;
  color: var(--p-muted);
}
.guest-foot {
  text-align: center;
}
.guest-foot a {
  color: var(--p-muted);
  font-size: 13px;
}
</style>
