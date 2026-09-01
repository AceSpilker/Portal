<script setup lang="ts">
import { useAuthStore } from '../stores/auth'
import {
  Grid as IconApps,
  Monitor as IconMonitor,
  MagicStick as IconAi,
  Share as IconFlow,
  SwitchButton as IconLogout,
} from '@element-plus/icons-vue'

const auth = useAuthStore()
const year = new Date().getFullYear()

function logout() {
  auth.logout()
  window.location.href = '/login'
}

/** 后续阶段的占位卡片 */
const upcoming = [
  { icon: IconApps, title: '应用管理', desc: '磁贴与分组、多入口配置', stage: 'P2' },
  { icon: IconMonitor, title: '服务器监控', desc: 'CPU / 内存 / 磁盘 / 网络', stage: 'P5' },
  { icon: IconAi, title: 'AI 助手', desc: '对话与意图导航', stage: 'M2' },
  { icon: IconFlow, title: 'Flow 自动化', desc: '触发器 → 条件 → 动作', stage: 'M2' },
]
</script>

<template>
  <el-container class="shell">
    <!-- 侧边导航 -->
    <aside class="side glass">
      <div class="logo"><span class="brand-text">Portal</span></div>
      <nav class="nav">
        <div class="nav-item active">
          <span class="dot" />首页
        </div>
        <div class="nav-item disabled">应用<span class="tag">P2</span></div>
        <div class="nav-item disabled">监控<span class="tag">P5</span></div>
        <div class="nav-item disabled">Flow<span class="tag">M2</span></div>
        <div class="nav-item disabled">AI<span class="tag">M2</span></div>
      </nav>
      <div class="side-foot">
        <span class="user">{{ auth.user?.username }}</span>
        <el-tooltip content="退出登录" placement="top">
          <el-button circle size="small" :icon="IconLogout" @click="logout" />
        </el-tooltip>
      </div>
    </aside>

    <!-- 主区 -->
    <el-main class="main">
      <header class="topbar">
        <h2>首页</h2>
        <span class="env">🏠 家庭内网</span>
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
          <el-icon :size="26" class="cell-icon"><component :is="item.icon" /></el-icon>
          <b>{{ item.title }}</b>
          <p>{{ item.desc }}</p>
          <span class="stage">{{ item.stage }}</span>
        </div>
      </section>

      <footer class="foot">© {{ year }} Portal · 自托管 NAS 门户</footer>
    </el-main>
  </el-container>
</template>

<style scoped>
.shell {
  min-height: 100vh;
  padding: 18px;
  gap: 18px;
  background:
    radial-gradient(900px 500px at 85% -10%, rgba(99, 102, 241, 0.14), transparent 60%),
    radial-gradient(700px 500px at -10% 110%, rgba(34, 211, 238, 0.08), transparent 60%);
}
.side {
  width: 212px;
  display: flex;
  flex-direction: column;
  padding: 18px 14px;
  position: sticky;
  top: 18px;
  height: calc(100vh - 36px);
}
.logo {
  font-size: 22px;
  padding: 4px 10px 18px;
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
  transition: background 0.2s, transform 0.15s;
}
.nav-item.active {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.25), rgba(139, 92, 246, 0.18));
  border: 1px solid rgba(129, 140, 248, 0.35);
}
.nav-item.active .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #22d3ee;
  box-shadow: 0 0 10px #22d3ee;
}
.nav-item.disabled {
  color: var(--p-muted);
  cursor: not-allowed;
}
.nav-item:not(.disabled):hover {
  background: rgba(255, 255, 255, 0.06);
  transform: translateX(2px);
}
.tag {
  margin-left: auto;
  font-size: 10.5px;
  color: var(--p-muted);
  border: 1px solid rgba(255, 255, 255, 0.12);
  padding: 0 7px;
  border-radius: 999px;
}
.side-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  padding: 12px 6px 0;
}
.user {
  font-size: 13.5px;
  color: var(--p-text);
}
.main {
  padding: 6px 4px;
}
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 6px 16px;
}
.topbar h2 {
  margin: 0;
  font-size: 20px;
}
.env {
  font-size: 12.5px;
  color: var(--p-muted);
  border: 1px solid var(--p-card-border);
  padding: 4px 12px;
  border-radius: 999px;
}
.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 26px 30px;
  margin-bottom: 18px;
}
.hero h1 {
  margin: 0 0 6px;
  font-size: 22px;
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
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.3), rgba(34, 211, 238, 0.2));
  border: 1px solid rgba(129, 140, 248, 0.4);
  white-space: nowrap;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 14px;
}
.cell {
  padding: 20px;
  position: relative;
}
.cell-icon {
  color: #818cf8;
  margin-bottom: 10px;
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
}
.foot {
  text-align: center;
  color: rgba(255, 255, 255, 0.25);
  font-size: 12px;
  padding: 26px 0 6px;
}
</style>
