<script setup lang="ts">
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

const auth = useAuthStore()
const year = new Date().getFullYear()

function logout() {
  auth.logout()
  window.location.href = '/login'
}

/** 后续阶段的占位卡片（彩色图标区分） */
const upcoming = [
  { icon: IconApps, title: '应用管理', desc: '磁贴与分组、多入口配置', stage: 'P2', color: '#5b5ff1', bg: 'rgba(91, 95, 241, 0.1)' },
  { icon: IconMonitor, title: '服务器监控', desc: 'CPU / 内存 / 磁盘 / 网络', stage: 'P5', color: '#06b6d4', bg: 'rgba(6, 182, 212, 0.1)' },
  { icon: IconAi, title: 'AI 助手', desc: '对话与意图导航', stage: 'M2', color: '#8b5cf6', bg: 'rgba(139, 92, 246, 0.1)' },
  { icon: IconFlow, title: 'Flow 自动化', desc: '触发器 → 条件 → 动作', stage: 'M2', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.12)' },
]

const navItems = [
  { icon: IconHome, label: '首页', active: true },
  { icon: IconApps, label: '应用', tag: 'P2', disabled: true },
  { icon: IconMonitor, label: '监控', tag: 'P5', disabled: true },
  { icon: IconFlow, label: 'Flow', tag: 'M2', disabled: true },
  { icon: IconAi, label: 'AI', tag: 'M2', disabled: true },
]

const tabs = [
  { icon: IconHome, label: '首页', active: true },
  { icon: IconApps, label: '应用', disabled: true },
  { icon: IconMonitor, label: '监控', disabled: true },
  { icon: IconFlow, label: 'Flow', disabled: true },
  { icon: IconAi, label: 'AI', disabled: true },
]
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
          :class="{ active: item.active, disabled: item.disabled, 'icon-only': isTablet }"
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

    <!-- 主区 -->
    <main class="main" :class="{ mobile: isMobile }">
      <header class="topbar">
        <h2>首页</h2>
        <div class="topbar-right">
          <span class="env">🏠 家庭内网</span>
          <el-button class="btn-logout-mobile" circle size="small" :icon="IconLogout" @click="logout" />
        </div>
      </header>

      <!-- 欢迎横幅 -->
      <section class="hero glass fade-up">
        <div>
          <h1>你好，{{ auth.user?.username }} 👋</h1>
          <p>这是 P0/P1 骨架完成后的样子——仪表盘磁贴将在 P4 阶段上线。</p>
        </div>
        <span class="pill">P0 · 骨架已就绪</span>
      </section>

      <!-- 占位卡片 -->
      <section class="grid stagger">
        <div v-for="item in upcoming" :key="item.title" class="cell glass hover-lift">
          <span class="cell-icon" :style="{ background: item.bg, color: item.color }">
            <el-icon :size="22"><component :is="item.icon" /></el-icon>
          </span>
          <b>{{ item.title }}</b>
          <p>{{ item.desc }}</p>
          <span class="stage">{{ item.stage }}</span>
        </div>
      </section>

      <footer class="foot">© {{ year }} Portal · 自托管 NAS 门户</footer>
    </main>

    <!-- 移动端底部 Tab 导航（M16-3，含安全区适配 M16-7） -->
    <nav class="tabbar">
      <div
        v-for="tab in tabs"
        :key="tab.label"
        class="tab"
        :class="{ active: tab.active, disabled: tab.disabled }"
      >
        <el-icon :size="20"><component :is="tab.icon" /></el-icon>
        <span>{{ tab.label }}</span>
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
  transition: background 0.2s, transform 0.15s, color 0.2s;
  white-space: nowrap;
}
.nav-item.active {
  background: linear-gradient(135deg, rgba(91, 95, 241, 0.12), rgba(139, 92, 246, 0.08));
  color: var(--p-primary);
  font-weight: 600;
}
.nav-item.active .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--p-primary);
  box-shadow: 0 0 8px rgba(91, 95, 241, 0.8);
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
.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: clamp(18px, 2.4vw, 30px);
  flex-shrink: 0;
  background:
    linear-gradient(120deg, rgba(91, 95, 241, 0.06), rgba(6, 182, 212, 0.05)),
    #fff;
}
.hero h1 {
  margin: 0 0 6px;
  font-size: clamp(19px, 2.2vw, 22px);
}
.hero p {
  margin: 0;
  color: var(--p-muted);
  font-size: 13.5px;
}
.pill {
  font-size: 12px;
  padding: 6px 14px;
  border-radius: 999px;
  color: var(--p-primary);
  background: rgba(91, 95, 241, 0.08);
  border: 1px solid rgba(91, 95, 241, 0.25);
  white-space: nowrap;
}
.grid {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  align-content: start;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(230px, 100%), 1fr));
  gap: clamp(10px, 1.4vw, 14px);
  padding: 2px;
}
.cell {
  padding: clamp(14px, 1.8vw, 20px);
  position: relative;
}
.cell-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  margin-bottom: 12px;
}
.cell b {
  display: block;
  margin-bottom: 4px;
}
.cell p {
  margin: 0;
  font-size: 12.5px;
  color: var(--p-muted);
}
.stage {
  position: absolute;
  top: 14px;
  right: 14px;
  font-size: 10.5px;
  color: var(--p-muted);
  border: 1px solid var(--p-card-border);
  border-radius: 999px;
  padding: 1px 8px;
  background: #fff;
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
  .hero {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
    padding: 18px;
  }
  .grid {
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
  .cell {
    padding: 14px;
  }
  .foot {
    padding-bottom: 10px;
  }
}
@media (max-width: 400px) {
  .grid {
    grid-template-columns: 1fr;
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
  transition: color 0.2s, transform 0.15s;
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
