<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ELEMENT_ICON_MAP } from '../utils/elementIcons'
import { useSettingsStore } from '../stores/settings'
import { useIconLibraryStore } from '../stores/iconLibrary'

export type IconPickKind = 'element' | 'custom'
export interface IconPick {
  kind: IconPickKind
  value: string
}

const { t } = useI18n()

/** 通用图标选择器：v-model 绑定图标名/自定义路径；@select 携带 kind 供调用方写入 icon_type */
const props = withDefaults(
  defineProps<{
    modelValue: string
    placeholder?: string
    maxHeight?: number
  }>(),
  { placeholder: '', maxHeight: 220 },
)

const emit = defineEmits<{
  (e: 'update:modelValue', v: string): void
  (e: 'select', v: IconPick): void
}>()

const settingsStore = useSettingsStore()
const iconLibrary = useIconLibraryStore()
onMounted(() => iconLibrary.load())

const search = ref('')
const ph = computed(() => props.placeholder || t('iconPicker.ph'))

const searching = computed(() => !!search.value.trim())
const kw = computed(() => search.value.trim().toLowerCase())

interface PickCell {
  key: string // element = 图标名；custom = 路径
  kind: IconPickKind
  name: string
  path?: string
  component?: unknown
  favorite: boolean
}

/** 统一网格：内置与自定义图标合并（按名称排序），自定义图标带角标便于识别 */
const allCells = computed<PickCell[]>(() => {
  const favs = settingsStore.iconFavorites
  const customs = iconLibrary.icons
    .filter((i) => i.source === 'custom')
    .map((i) => ({
      key: i.path ?? '',
      kind: 'custom' as const,
      name: i.name,
      path: i.path ?? '',
      component: undefined,
      favorite: favs.includes(i.path ?? ''),
    }))
  const builtins = iconLibrary.icons
    .filter((i) => i.source === 'builtin')
    .map((i) => ({
      key: i.element_name ?? i.name,
      kind: 'element' as const,
      name: i.name,
      component: ELEMENT_ICON_MAP[i.element_name ?? i.name],
      favorite: favs.includes(i.element_name ?? i.name),
    }))
  // 常用精选排最前（保持设置页 curated 的顺序），其余按名称排序
  const favRank = new Map(favs.map((key, idx) => [key, idx]))
  const rank = (c: PickCell) => favRank.get(c.key) ?? Number.MAX_SAFE_INTEGER
  return [...customs, ...builtins].sort((a, b) => {
    const diff = rank(a) - rank(b)
    return diff !== 0 ? diff : a.name.localeCompare(b.name)
  })
})

const gridCells = computed<PickCell[]>(() =>
  searching.value
    ? allCells.value.filter((c) => c.name.toLowerCase().includes(kw.value))
    : allCells.value,
)

function select(cell: PickCell) {
  const value = props.modelValue === cell.key ? '' : cell.key
  emit('update:modelValue', value)
  emit('select', { kind: cell.kind, value })
}
</script>

<template>
  <div class="icon-picker">
    <el-input v-model="search" :placeholder="ph" clearable class="picker-search" />
    <div class="picker-grid" :style="{ maxHeight: `${maxHeight}px` }">
      <button
        v-for="cell in gridCells"
        :key="`${cell.kind}-${cell.key}`"
        type="button"
        class="picker-cell"
        :class="{ active: modelValue === cell.key }"
        :title="cell.name"
        @click="select(cell)"
      >
        <img v-if="cell.kind === 'custom'" :src="cell.path" :alt="cell.name" class="picker-cell__img" />
        <component :is="cell.component" v-else class="picker-cell__svg" />
        <span v-if="cell.favorite" class="picker-cell__fav">★</span>
      </button>
      <div v-if="!gridCells.length" class="picker-empty">{{ t('iconPicker.noMatch') }}</div>
    </div>
  </div>
</template>

<style scoped>
.icon-picker {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.picker-search {
  margin-bottom: 2px;
}
.picker-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(38px, 1fr));
  gap: 4px;
  overflow-y: auto;
  padding: 4px 2px;
  border: 1px solid var(--p-card-border);
  border-radius: 10px;
  align-content: start;
}
.picker-cell {
  position: relative;
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
.picker-cell__img {
  width: 22px;
  height: 22px;
  object-fit: contain;
  border-radius: 4px;
}
.picker-cell__fav {
  position: absolute;
  right: 1px;
  bottom: 1px;
  font-size: 8px;
  line-height: 1;
  color: var(--p-primary);
}
.picker-empty {
  grid-column: 1 / -1;
  text-align: center;
  color: var(--p-muted);
  font-size: 12px;
  padding: 14px 0;
}
</style>
