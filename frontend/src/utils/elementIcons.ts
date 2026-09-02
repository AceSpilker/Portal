import type { Component } from 'vue'
import * as ElIcons from '@element-plus/icons-vue'

export interface ElementIconDef {
  name: string
  component: Component
}

/** Element Plus 全量图标（PascalCase 名 → 组件），应用图标「图标库」类型使用。 */
export const ELEMENT_ICONS: ElementIconDef[] = Object.entries(ElIcons)
  .filter(([name]) => /^[A-Z]/.test(name))
  .map(([name, component]) => ({ name, component: component as Component }))
  .sort((a, b) => a.name.localeCompare(b.name))

export const ELEMENT_ICON_MAP: Record<string, Component> = Object.fromEntries(
  ELEMENT_ICONS.map((i) => [i.name, i.component]),
)

/** 按名称模糊过滤（不区分大小写）。 */
export function filterElementIcons(keyword: string): ElementIconDef[] {
  const kw = keyword.trim().toLowerCase()
  if (!kw) return ELEMENT_ICONS
  return ELEMENT_ICONS.filter((i) => i.name.toLowerCase().includes(kw))
}
