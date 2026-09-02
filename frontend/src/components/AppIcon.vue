<script setup lang="ts">
import { computed } from 'vue'
import { ELEMENT_ICON_MAP } from '../utils/elementIcons'

/**
 * 应用图标统一渲染（P2.4）：
 * - url / upload → 图片（/icons 本地路径或外链）
 * - element → Element Plus 图标组件（icon 存 PascalCase 图标名）
 * - 其他（历史 emoji 数据）→ 文本字符
 */
const props = defineProps<{
  icon?: string | null
  iconType?: string
  size?: number
}>()

const isImage = computed(() => props.iconType === 'url' || props.iconType === 'upload')
const elIcon = computed(() =>
  props.iconType === 'element' && props.icon ? ELEMENT_ICON_MAP[props.icon] : undefined,
)
const px = computed(() => (props.size ? `${props.size}px` : undefined))
</script>

<template>
  <img
    v-if="isImage && icon"
    :src="icon"
    alt=""
    class="app-icon__img"
    :style="px ? { width: px, height: px } : undefined"
  />
  <component
    :is="elIcon"
    v-else-if="elIcon"
    class="app-icon__el"
    :style="{ width: px ?? '1em', height: px ?? '1em' }"
  />
  <span v-else class="app-icon__text">{{ icon || '🧩' }}</span>
</template>

<style scoped>
.app-icon__img {
  object-fit: contain;
}
.app-icon__text {
  line-height: 1;
}
</style>
