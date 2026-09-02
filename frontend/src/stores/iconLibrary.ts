import { defineStore } from 'pinia'
import { ref } from 'vue'
import { iconsApi } from '../api/icons'
import type { CustomIcon, CustomIconPayload } from '../api/icons'

/**
 * 自定义图标库状态：IconPicker / 设置页图标库管理共享。
 * 登录后由选择器首次使用时加载；管理页增删改后调用对应动作同步列表。
 */
export const useIconLibraryStore = defineStore('iconLibrary', () => {
  const customIcons = ref<CustomIcon[]>([])
  const loaded = ref(false)

  async function load(force = false) {
    if (loaded.value && !force) return
    try {
      customIcons.value = await iconsApi.list()
      loaded.value = true
    } catch {
      // 未登录等场景静默
    }
  }

  async function create(payload: CustomIconPayload) {
    const icon = await iconsApi.create(payload)
    customIcons.value = [...customIcons.value, icon].sort((a, b) =>
      a.name.localeCompare(b.name),
    )
    return icon
  }

  async function update(id: number, payload: Partial<CustomIconPayload>) {
    const icon = await iconsApi.update(id, payload)
    customIcons.value = customIcons.value.map((c) => (c.id === id ? icon : c))
    return icon
  }

  async function remove(id: number) {
    await iconsApi.remove(id)
    customIcons.value = customIcons.value.filter((c) => c.id !== id)
  }

  return { customIcons, loaded, load, create, update, remove }
})
