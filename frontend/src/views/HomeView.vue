<script setup lang="ts">
import { useAuthStore } from '../stores/auth'
import {
  Grid as IconApps,
  Monitor as IconMonitor,
  MagicStick as IconAi,
  Share as IconFlow,
} from '@element-plus/icons-vue'

const auth = useAuthStore()

/** 后续阶段的占位卡片（彩色图标区分） */
const upcoming = [
  { icon: IconApps, title: '应用管理', desc: '磁贴与分组、多入口配置', stage: 'P2', color: '#5b5ff1', bg: 'rgba(91, 95, 241, 0.1)' },
  { icon: IconMonitor, title: '服务器监控', desc: 'CPU / 内存 / 磁盘 / 网络', stage: 'P5', color: '#06b6d4', bg: 'rgba(6, 182, 212, 0.1)' },
  { icon: IconAi, title: 'AI 助手', desc: '对话与意图导航', stage: 'M2', color: '#8b5cf6', bg: 'rgba(139, 92, 246, 0.1)' },
  { icon: IconFlow, title: 'Flow 自动化', desc: '触发器 → 条件 → 动作', stage: 'M2', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.12)' },
]
</script>

<template>
  <div class="home">
    <!-- 欢迎横幅 -->
    <section class="hero glass fade-up">
      <div>
        <h1>你好，{{ auth.user?.username }} 👋</h1>
        <p>仪表盘磁贴将在 P4 阶段上线，现在可以先到「应用」页维护应用与入口。</p>
      </div>
      <span class="pill">P2 · 应用与入口管理已就绪</span>
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

    <footer class="foot">© {{ new Date().getFullYear() }} Portal · 自托管 NAS 门户</footer>
  </div>
</template>

<style scoped>
.home {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: clamp(10px, 1.4vw, 16px);
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

/* ===== 移动端适配（<768px）===== */
@media (max-width: 767px) {
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
}
@media (max-width: 400px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
