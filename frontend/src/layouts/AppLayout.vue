<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useSettingsStore } from '../stores/settings'
import { useEnvStore } from '../stores/env'
import { useMediaQuery } from '@vueuse/core'
import CommandPalette from '../components/CommandPalette.vue'
import {
  Grid as IconApps,
  Monitor as IconMonitor,
  MagicStick as IconAi,
  Suitcase as IconTools,
  Setting as IconSetting,
  Share as IconFlow,
  SwitchButton as IconLogout,
  HomeFilled as IconHome,
  ArrowDown as IconArrowDown,
  Search as IconSearch,
} from '@element-plus/icons-vue'

interface NavItem {
  icon: typeof IconHome
  label: string
  to?: string
  tag?: string
  disabled?: boolean
}

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const auth = useAuthStore()
const settingsStore = useSettingsStore()
const envStore = useEnvStore()
const paletteVisible = ref(false)
// 窗口 <1080px 时侧栏折叠为图标栏（桌面窄窗口行为，非移动端适配）
const isRail = useMediaQuery('(max-width: 1079px)')

onMounted(() => {
  settingsStore.load()
  // 网络环境自动识别 + 档案列表（顶栏切换器，M04-8/9）
  envStore.load()
})

/** 切换器展示的生效环境名（手动优先，其次自动识别结果） */
const envLabel = computed(() => {
  if (!envStore.loaded) return t('env.detecting')
  return envStore.effective?.name ?? t('env.autoNone')
})

const autoOptionLabel = computed(() =>
  envStore.autoProfile
    ? t('env.autoOption', { name: envStore.autoProfile.name })
    : t('env.autoNone'),
)

async function onEnvCommand(command: string | number) {
  try {
    await envStore.setManual(command === 'auto' ? null : Number(command))
  } catch {
    // 错误消息由请求拦截器统一提示
  }
}

/** 管理员额外显示监控（接口权限 A）与系统配置入口 */
const navItems = computed<NavItem[]>(() => [
  { icon: IconHome, label: t('nav.home'), to: '/' },
  { icon: IconApps, label: t('nav.apps'), to: '/apps' },
  ...(auth.isAdmin ? [{ icon: IconMonitor, label: t('nav.monitor'), to: '/monitor' }] : []),
  { icon: IconFlow, label: t('nav.flow'), tag: 'M2', disabled: true },
  { icon: IconAi, label: t('nav.ai'), tag: 'M2', disabled: true },
    { icon: IconTools, label: t('nav.tools'), to: '/tools' },
  ...(auth.isAdmin ? [{ icon: IconSetting, label: t('nav.settings'), to: '/settings' }] : []),
])

const pageTitle = computed(() => {
  const key = route.meta.titleKey as string | undefined
  return key ? t(key) : 'Portal'
})
const brand = computed(() => settingsStore.siteName)

/** 页面路由切换全局入场动画的 key */
const animKey = computed(() => route.fullPath)

function isActive(item: NavItem): boolean {
  if (!item.to) return false
  return item.to === '/' ? route.path === '/' : route.path.startsWith(item.to)
}

function onNav(item: NavItem) {
  if (item.disabled || !item.to || isActive(item)) return
  router.push(item.to)
}

function logout() {
  auth.logout()
  window.location.href = '/login'
}
</script>

<template>
  <div class="shell">
    <!-- 侧边导航（窗口较窄时折叠为图标栏） -->
    <aside class="side glass" :class="{ rail: isRail }">
      <div class="logo">
        <span class="brand-text">{{ brand }}</span>
        
      </div>
      <nav class="nav">
        <div
          v-for="item in navItems"
          :key="item.label"
          class="nav-item"
          :class="{
            active: isActive(item),
            disabled: item.disabled,
            'icon-only': isRail,
          }"
          @click="onNav(item)"
        >
          <el-icon :size="20"><component :is="item.icon" /></el-icon>
          <span class="nav-label">{{ item.label }}</span>
          <span v-if="item.tag" class="tag">{{ item.tag }}</span>
        </div>
      </nav>
      <div class="side-foot">
        <span class="user">{{ auth.user?.username }}</span>
        <el-tooltip :content="t('nav.logout')" placement="top" :disabled="false">
          <el-button circle size="small" :icon="IconLogout" @click="logout" />
        </el-tooltip>
      </div>
    </aside>

    <!-- 主区：页面内容由路由注入 -->
    <main class="main">
      <header class="topbar">
        <h2>{{ pageTitle }}</h2>
        <div class="topbar-right">
          <!-- 全局命令面板（M02-6）：Ctrl/Cmd+K 或点击唤起 -->
          <button type="button" class="palette-trigger" @click="paletteVisible = true">
            <el-icon :size="13"><IconSearch /></el-icon>
            <span class="palette-kbd">Ctrl K</span>
          </button>
          <!-- 环境切换器（M04-9）：手动覆盖自动识别，选择被记忆 -->
          <el-dropdown trigger="click" @command="onEnvCommand">
            <button type="button" class="env-badge" :title="t('env.currentIp', { ip: envStore.clientIp })">
              <span class="env-dot" :class="{ manual: !!envStore.manualProfile }" />
              <span class="env-name">{{ envLabel }}</span>
              <span v-if="envStore.manualProfile" class="env-mode">{{ t('env.badgeManual') }}</span>
              <el-icon :size="12"><IconArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="auto">
                  <span class="env-option" :class="{ active: !envStore.manualProfile }">
                    {{ autoOptionLabel }}
                  </span>
                </el-dropdown-item>
                <el-dropdown-item
                  v-for="p in envStore.profiles.filter((x) => x.enabled)"
                  :key="p.id"
                  :command="p.id"
                >
                  <span
                    class="env-option"
                    :class="{ active: envStore.manualProfile?.id === p.id }"
                  >
                    {{ p.name }}
                    <em v-if="p.match_type === 'default'">· {{ t('env.matchDefault') }}</em>
                  </span>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <div class="page">
        <router-view v-slot="{ Component }">
          <!-- 全局页面入场动画：keyed 元素替换触发纯 CSS 动画（不使用 transition 组件，避免编排死锁） -->
          <div :key="animKey" class="page-anim">
            <component :is="Component" />
          </div>
        </router-view>
      </div>
    </main>

    <!-- 全局命令面板（M02-6） -->
    <CommandPalette v-model="paletteVisible" />
  </div>
</template>

<style scoped>
.shell {
  height: 100vh;
  height: 100dvh;
  display: flex;
  gap: clamp(12px, 1.6vw, 18px);
  padding: clamp(12px, 1.6vw, 18px);
  box-sizing: border-box;
  overflow: hidden;
  background:
    radial-gradient(900px 500px at 85% -10%, color-mix(in srgb, var(--p-primary) 8%, transparent), transparent 60%),
    radial-gradient(700px 500px at -10% 110%, rgba(6, 182, 212, 0.06), transparent 60%);
}
.side {
  width: clamp(200px, 16vw, 216px);
  display: flex;
  flex-direction: column;
  padding: clamp(12px, 1.6vw, 18px) 14px;
  flex-shrink: 0;
  min-height: 0;
  overflow-y: auto;
}
.side.rail {
  width: 68px;
  padding: 14px 10px;
}
.logo {
  font-size: 22px;
  padding: 4px 10px 18px;
  text-align: center;
}
.side.rail .logo {
  padding: 4px 0 18px;
}
.nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 14px;
  border-radius: 12px;
  color: var(--p-text);
  font-size: 14px;
  cursor: pointer;
  transition:
    background 0.2s,
    transform 0.15s,
    color 0.2s;
  white-space: nowrap;
}
.nav-item.active {
  background: linear-gradient(135deg, color-mix(in srgb, var(--p-primary) 12%, transparent), rgba(139, 92, 246, 0.08));
  color: var(--p-primary);
  font-weight: 600;
}
.nav-item.disabled {
  color: var(--p-muted);
  cursor: not-allowed;
}
.nav-item:not(.disabled):hover {
  background: color-mix(in srgb, var(--p-primary) 7%, transparent);
  transform: translateX(2px);
}
.side.rail .nav-item {
  justify-content: center;
  padding: 11px 0;
}
.tag {
  margin-left: auto;
  font-size: 10.5px;
  color: var(--p-muted);
  border: 1px solid var(--p-card-border);
  padding: 0 7px;
  border-radius: 999px;
  background: var(--p-card);
}
.side-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-top: 1px solid var(--p-card-border);
  padding: 12px 6px 0;
}
.side.rail .side-foot {
  justify-content: center;
}
.user {
  font-size: 13.5px;
  color: var(--p-text);
}
.main {
  padding: 4px 6px;
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: clamp(10px, 1.4vw, 16px);
}
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 6px 0;
  flex-shrink: 0;
}
.topbar h2 {
  margin: 0;
  font-size: clamp(18px, 2vw, 20px);
  white-space: nowrap;
}
.topbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.palette-trigger {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--p-muted);
  border: 1px solid var(--p-card-border);
  background: var(--p-card);
  padding: 5px 10px;
  border-radius: 999px;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
}
.palette-trigger:hover {
  border-color: var(--p-primary);
  color: var(--p-primary);
}
.palette-kbd {
  font-size: 10.5px;
  border: 1px solid var(--p-card-border);
  border-radius: 5px;
  padding: 0 5px;
  background: var(--p-bg);
}
.env-badge {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 12.5px;
  color: var(--p-text);
  border: 1px solid var(--p-card-border);
  background: var(--p-card); /* 跟随卡片底色：暗色模式下不再保持纯白 */
  padding: 4px 12px;
  border-radius: 999px;
  white-space: nowrap;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;

}
.env-badge:hover {
  border-color: var(--p-primary);
  color: var(--p-primary);
}
.env-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #22c55e;
}
.env-dot.manual {
  background: var(--p-primary);
}
.env-name {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.env-mode {
  font-size: 10.5px;
  color: var(--p-primary);
  border: 1px solid color-mix(in srgb, var(--p-primary) 35%, transparent);
  background: color-mix(in srgb, var(--p-primary) 8%, transparent);
  padding: 0 6px;
  border-radius: 999px;
}
.env-option {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.env-option em {
  font-style: normal;
  font-size: 11px;
  color: var(--p-muted);
}
.env-option.active {
  color: var(--p-primary);
  font-weight: 600;
}
/* 路由页面容器：占满剩余空间并负责滚动 */
.page {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
/* 全局页面入场动画（keyed 元素替换即重放，纯 CSS 无编排风险） */
.page-anim {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  animation: page-in 0.35s cubic-bezier(0.22, 1, 0.36, 1);
}
@keyframes page-in {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
.page > * {
  flex-shrink: 0;
}
.foot {
  flex-shrink: 0;
  text-align: center;
  color: rgba(23, 33, 58, 0.3);
  font-size: 12px;
  padding: 10px 0 2px;
}

/* ===== 平板（768~1079）：侧栏收窄为图标栏 ===== */
@media (max-width: 1079px) and (min-width: 768px) {
  .side {
    width: 68px;
    padding: 14px 10px;
  }
  .side .logo {
    padding: 4px 0 18px;
    text-align: center;
  }
  .side .nav-item {
    justify-content: center;
    padding: 11px 0;
  }
  .side .nav-label,
  .side .tag,
  .side .user {
    display: none;
  }
  .side .side-foot {
    justify-content: center;
  }
}


</style>
