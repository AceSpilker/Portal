<script setup lang="ts">
/**
 * 全局命令面板（M02-6；dev-plan P4.4）：Ctrl/Cmd+K 唤起，模糊匹配
 * 名称/描述/标签，收藏优先，↑↓ 选择、回车直达、Esc 关闭。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Search as IconSearch } from '@element-plus/icons-vue'
import { portalApi } from '../api/portal'
import type { PortalApp } from '../api/portal'
import { searchApps } from '../utils/search'
import AppIcon from './AppIcon.vue'
import { useOpenApp } from '../composables/useOpenApp'
import { isMobile } from '../composables/useIsMobile'

const visible = defineModel<boolean>({ required: true })
const { t } = useI18n()
const { openApp } = useOpenApp()

const apps = ref<PortalApp[]>([])
const loaded = ref(false)
const query = ref('')
const active = ref(0)
const inputRef = ref<HTMLInputElement>()

const results = computed(() => searchApps(apps.value, query.value).slice(0, 9))

watch(visible, async (open) => {
  if (!open) return
  query.value = ''
  active.value = 0
  if (!loaded.value) {
    try {
      apps.value = await portalApi.listApps()
      loaded.value = true
    } catch (e) {
      ElMessage.error((e as Error).message)
      visible.value = false
      return
    }
  }
  await nextTick()
  inputRef.value?.focus()
})

watch(query, () => (active.value = 0))

function move(delta: number) {
  if (!results.value.length) return
  active.value = (active.value + delta + results.value.length) % results.value.length
}

function onKeydown(ev: KeyboardEvent) {
  if (ev.key === 'ArrowDown') {
    ev.preventDefault()
    move(1)
  } else if (ev.key === 'ArrowUp') {
    ev.preventDefault()
    move(-1)
  } else if (ev.key === 'Enter') {
    ev.preventDefault()
    choose(results.value[active.value])
  } else if (ev.key === 'Escape') {
    visible.value = false
  }
}

function choose(app: PortalApp | undefined) {
  if (!app) return
  visible.value = false
  openApp(app) // 多入口 → 全局智能解析浮层；单入口按 open_mode 打开
}

function onGlobalKey(ev: KeyboardEvent) {
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'k') {
    ev.preventDefault()
    visible.value = !visible.value
  }
}

onMounted(() => window.addEventListener('keydown', onGlobalKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onGlobalKey))
</script>

<template>
  <el-dialog
    v-model="visible"
    :width="isMobile ? '92%' : '520px'"
    :show-close="false"
    append-to-body
    class="palette-dialog"
  >
    <div class="palette">
      <div class="palette-input-row">
        <el-icon :size="16"><IconSearch /></el-icon>
        <input
          ref="inputRef"
          v-model="query"
          class="palette-input"
          :placeholder="t('home.palettePh')"
          @keydown="onKeydown"
        />
      </div>
      <div class="palette-list">
        <button
          v-for="(app, i) in results"
          :key="app.id"
          type="button"
          class="palette-item"
          :class="{ active: i === active }"
          @mousemove="active = i"
          @click="choose(app)"
        >
          <AppIcon :icon="app.icon" :icon-type="app.icon_type" :size="20" />
          <span class="pi-name">{{ app.name }}</span>
          <span v-if="app.favorite" class="pi-fav">★</span>
          <span class="pi-desc">{{ app.description }}</span>
        </button>
        <p v-if="query && !results.length" class="palette-empty">{{ t('home.paletteNoMatch') }}</p>
        <p v-else-if="!query" class="palette-empty">{{ t('home.paletteHint') }}</p>
      </div>
      <footer class="palette-foot">
        <span>↑↓ {{ t('home.paletteNav') }}</span>
        <span>Enter {{ t('home.paletteOpen') }}</span>
        <span>Esc {{ t('common.close') }}</span>
      </footer>
    </div>
  </el-dialog>
</template>

<style scoped>
.palette {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.palette-input-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--p-card-border);
  border-radius: 10px;
  color: var(--p-muted);
}
.palette-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 14.5px;
  color: var(--p-text);
}
.palette-list {
  max-height: 320px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.palette-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: var(--p-text);
  cursor: pointer;
  text-align: left;
}
.palette-item.active {
  background: color-mix(in srgb, var(--p-primary) 10%, transparent);
}
.pi-name {
  font-weight: 600;
  font-size: 13.5px;
  flex-shrink: 0;
}
.pi-fav {
  color: #f59e0b;
  font-size: 12px;
}
.pi-desc {
  font-size: 12px;
  color: var(--p-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.palette-empty {
  margin: 0;
  padding: 18px 0;
  text-align: center;
  color: var(--p-muted);
  font-size: 13px;
}
.palette-foot {
  display: flex;
  gap: 14px;
  font-size: 11.5px;
  color: var(--p-muted);
  border-top: 1px dashed var(--p-card-border);
  padding-top: 8px;
}
</style>
