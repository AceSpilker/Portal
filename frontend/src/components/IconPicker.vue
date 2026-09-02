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
}

/** 内置图标（来自图标库实体，可搜索） */
const builtinCells = computed<PickCell[]>(() =>
  iconLibrary.icons
    .filter((i) => i.source === 'builtin')
    .filter((i) => !searching.value || i.name.toLowerCase().includes(kw.value))
    .map((i) => ({
      key: i.element_name ?? i.name,
      kind: 'element' as const,
      name: i.name,
      component: ELEMENT_ICON_MAP[i.element_name ?? i.name],
    })),
)

/** 自定义图标 */
const customCells = computed<PickCell[]>(() =>
  iconLibrary.icons
    .filter((i) => i.source === 'custom')
    .filter((i) => !searching.value || i.name.toLowerCase().includes(kw.value))
    .map((i) => ({ key: i.path ?? '', kind: 'custom' as const, name: i.name, path: i.path ?? '' })),
)

/** 常用精选：内置名 / 自定义路径，均从图标库实体解析 */
const favorites = computed<PickCell[]>(() =>
  settingsStore.iconFavorites
    .map((key): PickCell | null => {
      if (key.startsWith('/icons/')) {
        const found = customCells.value.find((c) => c.key === key)
        return found ?? null
      }
      const found = builtinCells.value.find((c) => c.key === key)
      return found ?? null
    })
    .filter((f): f is PickCell => f !== null),
)

function select(kind: IconPickKind, value: string) {
  emit('update:modelValue', props.modelValue === value ? '' : value)
  emit('select', { kind, value: props.modelValue === value ? '' : value })
}
</script>

<template>
  <div class="icon-picker">
    <el-input v-model="search" :placeholder="ph" clearable class="picker-search" />
    <template v-if="!searching && favorites.length">
      <div class="picker-label">{{ t('iconPicker.favorites') }}</div>
      <div class="picker-grid" :style="{ maxHeight: `${Math.min(maxHeight, 120)}px` }">
        <button
          v-for="ic in favorites"
          :key="`fav-${ic.kind}-${ic.key}`"
          type="button"
          class="picker-cell"
          :class="{ active: modelValue === ic.key }"
          :title="ic.name"
          @click="select(ic.kind, ic.key)"
        >
          <img v-if="ic.kind === 'custom'" :src="ic.path" :alt="ic.name" class="picker-cell__img" />
          <component :is="ic.component" v-else class="picker-cell__svg" />
        </button>
      </div>
    </template>
    <template v-if="customCells.length">
      <div class="picker-label">{{ t('iconPicker.custom') }}</div>
      <div class="picker-grid" :style="{ maxHeight: `${Math.min(maxHeight, 120)}px` }">
        <button
          v-for="c in customCells"
          :key="`cus-${c.key}`"
          type="button"
          class="picker-cell"
          :class="{ active: modelValue === c.key }"
          :title="c.name"
          @click="select('custom', c.key)"
        >
          <img :src="c.path" :alt="c.name" class="picker-cell__img" />
        </button>
      </div>
    </template>
    <div class="picker-label">
      {{ searching ? t('iconPicker.searchResult', { n: builtinCells.length }) : t('iconPicker.all') }}
    </div>
    <div class="picker-grid" :style="{ maxHeight: `${maxHeight}px` }">
      <button
        v-for="ic in builtinCells"
        :key="ic.key"
        type="button"
        class="picker-cell"
        :class="{ active: modelValue === ic.key }"
        :title="ic.name"
        @click="select('element', ic.key)"
      >
        <component :is="ic.component" class="picker-cell__svg" />
      </button>
      <div v-if="searching && !builtinCells.length" class="picker-empty">{{ t('iconPicker.noMatch') }}</div>
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
.picker-label {
  font-size: 12px;
  color: var(--p-muted);
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
.picker-empty {
  grid-column: 1 / -1;
  text-align: center;
  color: var(--p-muted);
  font-size: 12px;
  padding: 14px 0;
}
</style>
