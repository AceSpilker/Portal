import { defineStore } from 'pinia'
import { ref } from 'vue'
import { iconsApi } from '../api/icons'
import type { IconItem } from '../api/icons'
import { ELEMENT_ICONS } from '../utils/elementIcons'

/**
 * 图标库状态（内置 + 自定义统一实体）：
 * - 首次加载时把前端 Element 图标名播种到后端（幂等：已删除的不会复活）；
 * - 管理页增删改后经动作同步列表。
 */
export const useIconLibraryStore = defineStore('iconLibrary', () => {
  const icons = ref<IconItem[]>([])
  const loaded = ref(false)

  async function load(force = false) {
    if (loaded.value && !force) return
    try {
      icons.value = await iconsApi.list()
      loaded.value = true
      await seedMissingBuiltins()
    } catch {
      // 未登录等场景静默
    }
  }

  /** 播种缺失的内置图标（升级新增的图标也会被补上；已删除的不会复活） */
  async function seedMissingBuiltins() {
    const known = new Set(
      icons.value.filter((i) => i.source === 'builtin').map((i) => i.element_name),
    )
    const missing = ELEMENT_ICONS.map((i) => i.name).filter((n) => !known.has(n))
    if (!missing.length) return
    const { seeded } = await iconsApi.seed(missing)
    if (seeded > 0) icons.value = await iconsApi.list()
  }

  async function create(payload: { name: string; filename?: string; data: string }) {
    const icon = await iconsApi.create(payload)
    icons.value = [...icons.value, icon]
    return icon
  }

  async function update(id: number, payload: { name?: string; filename?: string; data?: string }) {
    const icon = await iconsApi.update(id, payload)
    icons.value = icons.value.map((c) => (c.id === id ? icon : c))
    return icon
  }

  async function remove(id: number) {
    await iconsApi.remove(id)
    icons.value = icons.value.filter((c) => c.id !== id)
  }

  return { icons, loaded, load, create, update, remove }
})
