import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { settingsApi } from '../api/settings'

/**
 * 系统设置状态（P7.1）：
 * - 登录后由布局加载一次，供站点名、标签候选等全局消费；
 * - 设置页保存后调用 reload 立即生效。
 */
export const useSettingsStore = defineStore('settings', () => {
  const map = ref<Record<string, unknown>>({})
  const loaded = ref(false)

  async function load(force = false) {
    if (loaded.value && !force) return
    try {
      map.value = await settingsApi.getSettings()
      loaded.value = true
    } catch {
      // 未登录或接口异常时静默，组件侧使用默认值
    }
  }

  async function save(values: Record<string, unknown>) {
    await settingsApi.updateSettings(values)
    map.value = { ...map.value, ...values }
    loaded.value = true
  }

  /** 站点名称（侧栏 Logo 等位置显示） */
  const siteName = computed(() => (map.value['general.site_name'] as string) || 'Portal')
  /** 应用标签候选（新增/编辑应用时选择） */
  const tagOptions = computed(
    () => (map.value['apps.tag_options'] as string[] | undefined) ?? [],
  )

  return { map, loaded, load, save, siteName, tagOptions }
})
