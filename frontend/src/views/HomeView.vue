<script setup lang="ts">
/**
 * 首页仪表盘（M02；dev-plan P4）。
 *
 * - 分组区块 + 应用磁贴（图标/名称/状态点，P6 接入探活数据）；
 * - 拖拽排序（区块内磁贴 + 区块本身），位置即改即存（/api/me/layouts）；
 * - 卡片 1x/2x 宽度、收藏区置顶、收藏星标（POST /apps/{id}/favorite）；
 * - 打开方式：新标签 / 当前页 / iframe 内嵌；多入口走智能解析浮层（P3.8）；
 * - 时钟小组件 + 时段问候；移动端单列与触控目标 ≥44px。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { VueDraggable } from 'vue-draggable-plus'
import {
  CaretBottom as IconCollapse,
  CaretRight as IconExpand,
  Plus as IconPlus,
  Rank as IconDrag,
  Star as IconStar,
  StarFilled as IconStarFilled,
} from '@element-plus/icons-vue'
import { portalApi } from '../api/portal'
import type { Category, PortalApp } from '../api/portal'
import { layoutApi } from '../api/dashboard'
import { useAuthStore } from '../stores/auth'
import { useOpenApp } from '../composables/useOpenApp'
import AppIcon from '../components/AppIcon.vue'
import NasOverview from '../components/NasOverview.vue'
import {
  buildSections,
  DEFAULT_LAYOUT,
  parseLayout,
  reorderSubset,
  syncOrder,
  type DashboardLayoutData,
} from '../utils/layout'
import { formatClockDate, formatClockTime } from '../utils/clock'

const { t, locale } = useI18n()
const auth = useAuthStore()
const { openApp } = useOpenApp()

// ---- 数据 ----
const apps = ref<PortalApp[]>([])
const categories = ref<Category[]>([])
const loading = ref(false)

// ---- 布局（P4.2/4.3）----
const layout = ref<DashboardLayoutData>({ ...DEFAULT_LAYOUT })
const sections = ref<{ key: string; title: string; collapsed: boolean; apps: PortalApp[] }[]>([])
const collapsedDraft = ref<Record<string, boolean>>({})

function rebuildSections() {
  layout.value.order = syncOrder(layout.value.order, apps.value)
  sections.value = buildSections(apps.value, categories.value, layout.value)
  collapsedDraft.value = Object.fromEntries(sections.value.map((s) => [s.key, s.collapsed]))
}

async function load() {
  loading.value = true
  try {
    const [appList, catList, layouts] = await Promise.all([
      portalApi.listApps(),
      portalApi.listCategories(),
      layoutApi.getMyLayouts(),
    ])
    apps.value = appList
    categories.value = catList
    const mine = layouts.find((l) => l.tab === 'default')
    layout.value = parseLayout(mine?.layout)
    rebuildSections()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

function persistLayout() {
  layoutApi.saveMyLayout('default', { ...layout.value }).catch((e) => ElMessage.error((e as Error).message))
}

// ---- 打开方式（P4.1）----
function onTileClick(app: PortalApp) {
  openApp(app)
}

// ---- 收藏（P4.5）----
async function toggleFavorite(app: PortalApp) {
  try {
    const r = await portalApi.toggleFavorite(app.id)
    app.favorite = r.favorite
    rebuildSections() // 收藏区置顶联动
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

// ---- 卡片尺寸（P4.3）----
function toggleSize(app: PortalApp) {
  const key = String(app.id)
  layout.value.sizes[key] = layout.value.sizes[key] === 2 ? 1 : 2
  persistLayout()
}

// ---- 折叠（M02-4）----
function toggleCollapse(key: string) {
  collapsedDraft.value[key] = !collapsedDraft.value[key]
  layout.value.collapsed[key] = collapsedDraft.value[key]
  persistLayout()
}

// ---- 拖拽排序（P4.2）----
let saveTimer: number | undefined
function persistSoon() {
  window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(persistLayout, 400)
}

function onTilesDragEnd() {
  // 各区块（含收藏区）按拖拽后的局部顺序回写全局扁平顺序
  let order = layout.value.order
  for (const s of sections.value) {
    order = reorderSubset(order, s.apps.map((a) => String(a.id)))
  }
  layout.value.order = order
  persistSoon()
}

function onSectionsDragEnd() {
  layout.value.sections = sections.value.map((s) => s.key)
  persistSoon()
}

// ---- 时钟小组件（P4.7；032 增强为年月日+时分秒+星期，每秒跳）----
// 本地时钟每秒自跳，不走后端接口：网络往返只会让显示滞后于真实时间
const now = ref(new Date())
let clockTimer: number | undefined
const clockText = computed(() => formatClockTime(now.value, locale.value))
const dateText = computed(() => formatClockDate(now.value, locale.value))
const greetingKey = computed(() => {
  const h = now.value.getHours()
  if (h < 5) return 'home.greetNight'
  if (h < 9) return 'home.greetMorning'
  if (h < 12) return 'home.greetForenoon'
  if (h < 14) return 'home.greetNoon'
  if (h < 18) return 'home.greetAfternoon'
  return 'home.greetEvening'
})

onMounted(() => {
  load()
  clockTimer = window.setInterval(() => (now.value = new Date()), 1_000)
})
onBeforeUnmount(() => window.clearInterval(clockTimer))
</script>

<template>
  <div class="home" v-loading="loading">
    <!-- 欢迎横幅 + 时钟小组件（P4.7） -->
    <section class="hero glass fade-up">
      <div class="hero-text">
        <h1>{{ t(greetingKey) }}，{{ auth.user?.username ?? '' }} 👋</h1>
        <p>{{ t('home.heroText') }}</p>
      </div>
      <div class="hero-side">
        <!-- NAS 资源速览（M02-12；P5.6，仅管理员） -->
        <NasOverview v-if="auth.isAdmin" class="nas-widget" />
        <div class="clock" :title="dateText">
          <span class="clock-time">{{ clockText }}</span>
          <span class="clock-date">{{ dateText }}</span>
        </div>
      </div>
    </section>

    <!-- 区块列表：收藏区置顶 + 分组区块，支持区块拖拽排序 -->
    <VueDraggable
      v-model="sections"
      handle=".sec-handle"
      class="sections"
      @end="onSectionsDragEnd"
    >
      <section v-for="sec in sections" :key="sec.key" class="section glass">
        <header class="sec-head">
          <el-icon class="sec-handle" :size="14"><IconDrag /></el-icon>
          <button type="button" class="sec-toggle" @click="toggleCollapse(sec.key)">
            <el-icon :size="13">
              <component :is="collapsedDraft[sec.key] ? IconExpand : IconCollapse" />
            </el-icon>
          </button>
          <h3>
            <el-icon v-if="sec.key === 'fav'" class="sec-fav-icon"><IconStarFilled /></el-icon>
            {{ sec.key === 'fav' ? t('home.favSection') : sec.key === 'none' ? t('apps.uncategorized') : sec.title }}
            <span class="sec-count">{{ sec.apps.length }}</span>
          </h3>
        </header>

        <!-- 区块内磁贴拖拽（收藏区亦可调序）；空态提示置于拖拽容器外 -->
        <div v-show="!collapsedDraft[sec.key]" class="tiles-wrap">
          <VueDraggable v-model="sec.apps" class="tiles" :animation="160" @end="onTilesDragEnd">
            <button
              v-for="app in sec.apps"
              :key="app.id"
              type="button"
              class="tile"
              :class="{ wide: layout.sizes[String(app.id)] === 2 }"
              :title="app.name"
              @click="onTileClick(app)"
            >
              <span class="tile-icon">
                <AppIcon :icon="app.icon" :icon-type="app.icon_type" :size="30" />
                <span class="status-dot unknown" :title="t('home.statusPending')" />
              </span>
              <span class="tile-name">{{ app.name }}</span>
              <span v-if="app.description" class="tile-desc">{{ app.description }}</span>
              <!-- 悬停操作：收藏 / 尺寸（阻止冒泡） -->
              <span class="tile-ops" @click.stop>
                <button
                  type="button"
                  class="tile-op"
                  :class="{ active: app.favorite }"
                  :title="t('home.favToggle')"
                  @click="toggleFavorite(app)"
                >
                  <el-icon :size="12">
                    <component :is="app.favorite ? IconStarFilled : IconStar" />
                  </el-icon>
                </button>
                <button
                  type="button"
                  class="tile-op"
                  :title="t('home.sizeToggle')"
                  @click="toggleSize(app)"
                >
                  <span class="size-glyph" :class="{ wide: layout.sizes[String(app.id)] === 2 }" />
                </button>
              </span>
            </button>
          </VueDraggable>
          <p v-if="!sec.apps.length" class="tile-empty">{{ t('common.noData') }}</p>
        </div>
      </section>
    </VueDraggable>

    <!-- 空状态 -->
    <section v-if="!loading && !sections.length" class="empty glass">
      <el-icon :size="34"><IconPlus /></el-icon>
      <p>{{ t('home.emptyTip') }}</p>
      <el-button type="primary" class="btn-gradient" @click="$router.push('/apps')">
        {{ t('home.emptyGo') }}
      </el-button>
    </section>

    <footer class="foot">© {{ new Date().getFullYear() }} Portal · {{ t('home.copyright') }}</footer>
  </div>
</template>

<style scoped>
.home {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: clamp(10px, 1.4vw, 16px);
  overflow-y: auto;
  padding-bottom: 4px;
}
.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: clamp(16px, 2.2vw, 26px);
  flex-shrink: 0;
  background:
    linear-gradient(120deg, color-mix(in srgb, var(--p-primary) 6%, transparent), rgba(6, 182, 212, 0.05)),
    var(--p-card);
}
.hero-text h1 {
  margin: 0 0 6px;
  font-size: clamp(18px, 2vw, 21px);
}
.hero-text p {
  margin: 0;
  color: var(--p-muted);
  font-size: 13px;
}
.hero-side {
  display: flex;
  align-items: center;
  gap: clamp(16px, 3vw, 34px);
  flex-shrink: 0;
}
.clock {
  text-align: right;
  flex-shrink: 0;
}
.clock-time {
  display: block;
  /* 数字宽度在不同回退字体下不完全等宽（"1"偏窄），固定最小宽度避免每秒抖动布局 */
  min-width: 4.6em;
  text-align: right;
  font-size: clamp(24px, 3vw, 34px);
  font-weight: 800;
  letter-spacing: 1px;
  background: linear-gradient(120deg, var(--p-primary), var(--p-primary-2));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  font-variant-numeric: tabular-nums;
}
.clock-date {
  font-size: 12px;
  color: var(--p-muted);
}
/* ---- 区块 ---- */
.sections {
  display: flex;
  flex-direction: column;
  gap: clamp(10px, 1.4vw, 14px);
}
.section {
  padding: clamp(12px, 1.6vw, 18px);
}
.sec-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.sec-handle {
  color: var(--p-muted);
  cursor: grab;
}
.sec-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--p-muted);
  cursor: pointer;
}
.sec-toggle:hover {
  background: color-mix(in srgb, var(--p-primary) 10%, transparent);
  color: var(--p-primary);
}
.sec-head h3 {
  margin: 0;
  font-size: 15px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.sec-fav-icon {
  color: #f59e0b;
}
.sec-count {
  font-size: 11px;
  color: var(--p-muted);
  border: 1px solid var(--p-card-border);
  border-radius: 999px;
  padding: 0 7px;
}
/* ---- 磁贴 ---- */
.tiles-wrap {
  min-height: 20px;
}
.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(148px, 1fr));
  gap: clamp(8px, 1.1vw, 12px);
  min-height: 20px;
}
.tile {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  min-height: 96px;
  padding: 14px;
  border: 1px solid var(--p-card-border);
  border-radius: 14px;
  background: var(--p-card);
  color: var(--p-text);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s, transform 0.15s, box-shadow 0.15s;
}
.tile.wide {
  grid-column: span 2;
}
.tile:hover {
  border-color: var(--p-primary);
  transform: translateY(-2px);
  box-shadow: 0 10px 24px rgba(23, 43, 99, 0.1);
}
.tile-icon {
  position: relative;
  display: inline-flex;
}
.status-dot {
  position: absolute;
  right: -3px;
  bottom: -1px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  border: 2px solid var(--p-card);
}
.status-dot.unknown {
  background: #9aa3b8;
}
.tile-name {
  font-weight: 600;
  font-size: 13.5px;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tile-desc {
  font-size: 11.5px;
  color: var(--p-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}
.tile-ops {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.15s;
}
.tile:hover .tile-ops {
  opacity: 1;
}
.tile-op {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: 7px;
  background: rgba(23, 33, 58, 0.06);
  color: var(--p-muted);
  cursor: pointer;
}
.tile-op:hover,
.tile-op.active {
  color: var(--p-primary);
  background: color-mix(in srgb, var(--p-primary) 12%, transparent);
}
.tile-op.active {
  color: #f59e0b;
}
.size-glyph {
  width: 8px;
  height: 8px;
  border: 1.5px solid currentColor;
  border-radius: 2px;
}
.size-glyph.wide {
  width: 14px;
}
.tile-empty {
  color: var(--p-muted);
  font-size: 12.5px;
  padding: 8px 0;
}
/* ---- 空状态 / 底部 ---- */
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--p-muted);
}
.empty p {
  margin: 0;
  font-size: 13.5px;
}
.foot {
  flex-shrink: 0;
  text-align: center;
  color: rgba(127, 137, 160, 0.8);
  font-size: 12px;
  padding: 6px 0 2px;
}
/* ---- 底部 ---- */

/* ===== 移动端（P4.8：<768px 单列，触控目标 ≥44px）===== */
@media (max-width: 767px) {
  .hero {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  .clock {
    text-align: left;
  }
  .hero-side {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }
  .tiles {
    grid-template-columns: 1fr 1fr;
  }
  .tile {
    min-height: 76px;
    padding: 12px;
  }
  .tile.wide {
    grid-column: span 2;
  }
  .tile-desc {
    display: none;
  }
  /* 悬停操作在触屏上常显（M16 触控目标 ≥44px） */
  .tile-ops {
    opacity: 1;
  }
  .tile-op {
    width: 44px;
    height: 44px;
  }
  .sec-handle {
    display: none;
  }
}
@media (max-width: 400px) {
  .tiles {
    grid-template-columns: 1fr;
  }
  .tile.wide {
    grid-column: span 1;
  }
}
</style>
