/**
 * 外观主题（M02-18/19/20；dev-plan P4.6）。
 *
 * 在 App.vue 挂载一次：监听系统偏好与外观设置，实时落到 <html>；
 * 外观设置未加载完成前保持默认（亮色 / 默认主题色 / 无壁纸）。
 */
import { onBeforeUnmount, onMounted, watch } from 'vue'
import { useSettingsStore } from '../stores/settings'
import { applyTheme, type AppearanceSettings, type DarkMode, type WallpaperType } from '../utils/theme'

export function useTheme() {
  const settingsStore = useSettingsStore()
  let mql: MediaQueryList | null = null
  const onSystemChange = () => sync()

  function current(): AppearanceSettings {
    const map = settingsStore.map
    return {
      themeColor: (map['appearance.theme_color'] as string) || '#5b5ff1',
      darkMode: (map['appearance.dark_mode'] as DarkMode) || 'auto',
      wallpaperType: (map['appearance.wallpaper_type'] as WallpaperType) || 'none',
      wallpaperValue: (map['appearance.wallpaper_value'] as string) || '',
      wallpaperBlur: (map['appearance.wallpaper_blur'] as number) ?? 0,
      wallpaperMask: (map['appearance.wallpaper_mask'] as number) ?? 35,
    }
  }

  function sync() {
    applyTheme(current(), window.matchMedia('(prefers-color-scheme: dark)').matches)
    // 壁纸层变量挂在 body 上的挂载点（App.vue 渲染 .wallpaper-layer 时读取）
    const el = document.documentElement
    const style = wallpaperVars()
    for (const [k, v] of Object.entries(style)) el.style.setProperty(k, v)
  }

  function wallpaperVars(): Record<string, string> {
    const s = current()
    if (s.wallpaperType === 'none' || !s.wallpaperValue) {
      return { '--p-wallpaper-bg': 'none', '--p-wallpaper-filter': 'none', '--p-wallpaper-opacity': '0' }
    }
    const bg =
      s.wallpaperType === 'image'
        ? `url("${s.wallpaperValue}") center/cover no-repeat`
        : s.wallpaperValue
    return {
      '--p-wallpaper-bg': bg,
      '--p-wallpaper-filter': s.wallpaperBlur > 0 ? `blur(${s.wallpaperBlur}px)` : 'none',
      '--p-wallpaper-opacity': String(1 - s.wallpaperMask / 100),
    }
  }

  onMounted(() => {
    mql = window.matchMedia('(prefers-color-scheme: dark)')
    mql.addEventListener('change', onSystemChange)
    sync()
  })
  onBeforeUnmount(() => mql?.removeEventListener('change', onSystemChange))
  watch(() => settingsStore.map, sync, { deep: true })
}
