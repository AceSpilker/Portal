<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { isMobile, isTablet } from '../composables/useIsMobile'
import {
  Grid as IconApps,
  Monitor as IconMonitor,
  MagicStick as IconAi,
  Share as IconFlow,
  SwitchButton as IconLogout,
  HomeFilled as IconHome,
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
const auth = useAuthStore()

const navItems: NavItem[] = [
  { icon: IconHome, label: '首页', to: '/' },
  { icon: IconApps, label: '应用', to: '/apps' },
  { icon: IconMonitor, label: '监控', tag: 'P5', disabled: true },
  { icon: IconFlow, label: 'Flow', tag: 'M2', disabled: true },
  { icon: IconAi, label: 'AI', tag: 'M2', disabled: true },
]

const pageTitle = computed(() => (route.meta.title as string | undefined) ?? 'Portal')

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
  <div class="shell" :class="{ mobile: isMobile }">
    <!-- 桌面/平板侧边导航（平板为图标栏；移动端隐藏，改用底部 Tab） -->
    <aside class="side glass" :class="{ rail: isTablet }">
      <div class="logo">
        <span v-if="!isTablet" class="brand-text">Portal</span>
        <span v-else class="brand-dot" />
      </div>
      <nav class="nav">
        <div
          v-for="item in navItems"
          :key="item.label"
          class="nav-item"
          :class="{
            active: isActive(item),
            disabled: item.disabled,
            'icon-only': isTablet,
          }"
          @click="onNav(item)"
        >
          <el-icon :size="20"><component :is="item.icon" /></el-icon>
          <span v-if="!isTablet" class="nav-label">{{ item.label }}</span>
          <span v-if="item.tag && !isTablet" class="tag">{{ item.tag }}</span>
        </div>
      </nav>
      <div class="side-foot">
        <span v-if="!isTablet" class="user">{{ auth.user?.username }}</span>
        <el-tooltip content="退出登录" placement="top" :disabled="isTablet">
          <el-button circle size="small" :icon="IconLogout" @click="logout" />
        </el-tooltip>
      </div>
    </aside>

    <!-- 主区：页面内容由路由注入 -->
    <main class="main" :class="{ mobile: isMobile }">
      <header class="topbar">
        <h2>{{ pageTitle }}</h2>
        <div class="topbar-right">
          <span class="env">🏠 家庭内网</span>
          <el-button
            class="btn-logout-mobile"
            circle
            size="small"
            :icon="IconLogout"
            @click="logout"
          />
        </div>
      </header>

      <div class="page">
        <router-view />
      </div>
    </main>

    <!-- 移动端底部 Tab 导航（M16-3，含安全区适配 M16-7） -->
    <nav class="tabbar">
      <div
        v-for="item in navItems"
        :key="item.label"
        class="tab"
        :class="{ active: isActive(item), disabled: item.disabled }"
        @click="onNav(item)"
      >
        <el-icon :size="20"><component :is="item.icon" /></el-icon>
        <span>{{ item.label }}</span>
      </div>
    </nav>
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
    radial-gradient(900px 500px at 85% -10%, rgba(91, 95, 241, 0.08), transparent 60%),
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
  background: linear-gradient(135deg, rgba(91, 95, 241, 0.12), rgba(139, 92, 246, 0.08));
  color: var(--p-primary);
  font-weight: 600;
}
.nav-item.disabled {
  color: var(--p-muted);
  cursor: not-allowed;
}
.nav-item:not(.disabled):hover {
  background: rgba(91, 95, 241, 0.07);
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
  background: #fff;
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
}
.topbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.btn-logout-mobile {
  display: none;
}
.env {
  font-size: 12.5px;
  color: var(--p-muted);
  border: 1px solid var(--p-card-border);
  background: #fff;
  padding: 4px 12px;
  border-radius: 999px;
  white-space: nowrap;
}
/* 路由页面容器：占满剩余空间并负责滚动 */
.page {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
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

/* ===== 移动端适配（M16 / <768px）===== */
@media (max-width: 767px) {
  .side {
    display: none;
  }
  .tabbar {
    display: flex;
  }
  .btn-logout-mobile {
    display: inline-flex;
  }
  .shell {
    padding: 12px 12px calc(78px + env(safe-area-inset-bottom));
  }
  .topbar h2 {
    font-size: 18px;
  }
}

/* ===== 底部 Tab 导航（移动端；桌面隐藏） ===== */
@media (min-width: 768px) {
  .tabbar {
    display: none;
  }
}
.tabbar {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  justify-content: space-around;
  padding: 8px 0 calc(8px + env(safe-area-inset-bottom));
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-top: 1px solid var(--p-card-border);
  box-shadow: 0 -8px 30px rgba(23, 43, 99, 0.06);
  z-index: 30;
}
.tab {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  font-size: 11px;
  color: var(--p-muted);
  min-width: 58px;
  min-height: 44px;
  justify-content: center;
  cursor: pointer;
  transition:
    color 0.2s,
    transform 0.15s;
}
.tab:active {
  transform: scale(0.92);
}
.tab.active {
  color: var(--p-primary);
  font-weight: 600;
}
.tab.disabled {
  opacity: 0.38;
}
</style>
