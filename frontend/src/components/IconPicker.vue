<script setup lang="ts">
import { computed, ref } from 'vue'
import { ELEMENT_ICONS, ELEMENT_ICON_MAP, filterElementIcons } from '../utils/elementIcons'
import { useSettingsStore } from '../stores/settings'

/**
 * 通用图标选择器（Element Plus 图标库）：
 * - v-model 绑定图标名（PascalCase，如 "Monitor"）
 * - 无关键字时先展示「常用」（系统配置 apps.icon_favorites 精选），再展示全量
 * - 搜索按名称模糊过滤；通过 maxHeight 控制嵌入抽屉/弹窗时的占高
 */
const props = withDefaults(
  defineProps<{
    modelValue: string
    placeholder?: string
    maxHeight?: number
  }>(),
  { placeholder: '搜索图标名，如 monitor / folder', maxHeight: 220 },
)

const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>()

const settingsStore = useSettingsStore()
const search = ref('')

const searching = computed(() => !!search.value.trim())
const filtered = computed(() => filterElementIcons(search.value))
const favorites = computed(() =>
  settingsStore.iconFavorites
    .filter((name) => ELEMENT_ICON_MAP[name])
    .map((name) => ({ name, component: ELEMENT_ICON_MAP[name] })),
)
const allList = computed(() => ELEMENT_ICONS)
const gridList = computed(() => (searching.value ? filtered.value : allList.value))

function select(name: string) {
  emit('update:modelValue', name === props.modelValue ? '' : name)
}
</script>

<template>
  <div class="icon-picker">
    <el-input v-model="search" :placeholder="placeholder" clearable />
    <template v-if="!searching && favorites.length">
      <div class="picker-label">常用</div>
      <div class="picker-grid" :style="{ maxHeight: `${Math.min(maxHeight, 120)}px` }">
        <button
          v-for="ic in favorites"
          :key="`fav-${ic.name}`"
          type="button"
          class="picker-cell"
          :class="{ active: modelValue === ic.name }"
          :title="ic.name"
          @click="select(ic.name)"
        >
          <component :is="ic.component" class="picker-cell__svg" />
        </button>
      </div>
    </template>
    <div class="picker-label">
      {{ searching ? `搜索结果（${filtered.length}）` : '全部图标' }}
    </div>
    <div class="picker-grid" :style="{ maxHeight: `${maxHeight}px` }">
      <button
        v-for="ic in gridList"
        :key="ic.name"
        type="button"
        class="picker-cell"
        :class="{ active: modelValue === ic.name }"
        :title="ic.name"
        @click="select(ic.name)"
      >
        <component :is="ic.component" class="picker-cell__svg" />
      </button>
      <div v-if="searching && !filtered.length" class="picker-empty">没有匹配的图标</div>
    </div>
  </div>
</template>

<style scoped>
.icon-picker {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.picker-label {
  font-size: 12px;
  color: var(--p-muted);
}
.picker-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(38px, 1fr));
  gap: 4px;
  overflow-y: auto;
  padding: 2px;
  border: 1px solid var(--p-card-border);
  border-radius: 10px;
  align-content: start;
}
.picker-cell {
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--p-text);
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.picker-cell:hover {
  background: rgba(91, 95, 241, 0.08);
  color: var(--p-primary);
}
.picker-cell.active {
  background: rgba(91, 95, 241, 0.14);
  color: var(--p-primary);
  border-color: var(--p-primary);
}
.picker-cell__svg {
  width: 20px;
  height: 20px;
}
.picker-empty {
  grid-column: 1 / -1;
  text-align: center;
  color: var(--p-muted);
  font-size: 12px;
  padding: 14px 0;
}
</style>
