<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ELEMENT_ICONS, ELEMENT_ICON_MAP, filterElementIcons } from '../utils/elementIcons'
import { useSettingsStore } from '../stores/settings'
import { useIconLibraryStore } from '../stores/iconLibrary'

export type IconPickKind = 'element' | 'custom'
export interface IconPick {
  kind: IconPickKind
  value: string
}

/**
 * 通用图标选择器：
 * - v-model 选中值（内置图标 = PascalCase 名；自定义图标 = /icons/ 路径）
 * - @select 额外携带 kind，调用方据此写入对应的 icon_type
 * - 分区展示：常用（apps.icon_favorites 精选）/ 自定义（图标库管理）/ 全部内置
 */
const props = withDefaults(
  defineProps<{
    modelValue: string
    placeholder?: string
    maxHeight?: number
  }>(),
  { placeholder: '搜索图标名，如 monitor / folder', maxHeight: 220 },
)

const emit = defineEmits<{
  (e: 'update:modelValue', v: string): void
  (e: 'select', v: IconPick): void
}>()

const settingsStore = useSettingsStore()
const iconLibrary = useIconLibraryStore()
onMounted(() => iconLibrary.load())

const search = ref('')

const searching = computed(() => !!search.value.trim())
const filteredElement = computed(() => filterElementIcons(search.value))

interface FavCell {
  key: string
  kind: IconPickKind
  name: string
  path?: string
  component?: unknown
}

/** 常用精选：既可能是内置图标名，也可能是自定义图标路径（/icons/ 开头） */
const favorites = computed<FavCell[]>(() =>
  settingsStore.iconFavorites
    .map((key): FavCell | null => {
      if (key.startsWith('/icons/')) {
        const c = iconLibrary.customIcons.find((x) => x.path === key)
        return c ? { key, kind: 'custom', name: c.name, path: c.path } : null
      }
      const comp = ELEMENT_ICON_MAP[key]
      return comp ? { key, kind: 'element', name: key, component: comp } : null
    })
    .filter((f): f is FavCell => f !== null),
)
const customList = computed(() =>
  iconLibrary.customIcons
    .filter((c) => !searching.value || c.name.toLowerCase().includes(search.value.trim().toLowerCase()))
    .map((c) => ({ name: c.name, path: c.path })),
)
const elementList = computed(() =>
  searching.value ? filteredElement.value : ELEMENT_ICONS,
)

function select(kind: IconPickKind, value: string) {
  emit('update:modelValue', props.modelValue === value ? '' : value)
  emit('select', { kind, value: props.modelValue === value ? '' : value })
}
</script>

<template>
  <div class="icon-picker">
    <el-input v-model="search" :placeholder="placeholder" clearable class="picker-search" />
    <template v-if="!searching && favorites.length">
      <div class="picker-label">常用</div>
      <div class="picker-grid" :style="{ maxHeight: `${Math.min(maxHeight, 120)}px` }">
        <button
          v-for="ic in favorites"
          :key="`fav-${ic.key}`"
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
    <template v-if="customList.length">
      <div class="picker-label">自定义</div>
      <div class="picker-grid" :style="{ maxHeight: `${Math.min(maxHeight, 120)}px` }">
        <button
          v-for="c in customList"
          :key="`cus-${c.path}`"
          type="button"
          class="picker-cell"
          :class="{ active: modelValue === c.path }"
          :title="c.name"
          @click="select('custom', c.path)"
        >
          <img :src="c.path" :alt="c.name" class="picker-cell__img" />
        </button>
      </div>
    </template>
    <div class="picker-label">
      {{ searching ? `内置图标 · 搜索结果（${filteredElement.length}）` : '内置图标' }}
    </div>
    <div class="picker-grid" :style="{ maxHeight: `${maxHeight}px` }">
      <button
        v-for="ic in elementList"
        :key="ic.name"
        type="button"
        class="picker-cell"
        :class="{ active: modelValue === ic.name }"
        :title="ic.name"
        @click="select('element', ic.name)"
      >
        <component :is="ic.component" class="picker-cell__svg" />
      </button>
      <div v-if="searching && !filteredElement.length" class="picker-empty">没有匹配的图标</div>
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
