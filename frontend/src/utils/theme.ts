/**
 * 主题应用逻辑（M02-18/19/20；dev-plan P4.6）。
 *
 * 纯函数供单测：resolveDark 输出最终是否暗色（auto 跟随系统 / light / dark）；
 * applyTheme 把结果落到 DOM（html data-theme + EP 变量 + 主题色派生）与壁纸层变量。
 */

export type DarkMode = 'auto' | 'light' | 'dark'
export type WallpaperType = 'none' | 'solid' | 'gradient' | 'image'

export interface AppearanceSettings {
  themeColor: string
  darkMode: DarkMode
  wallpaperType: WallpaperType
  wallpaperValue: string
  wallpaperBlur: number
  wallpaperMask: number
}

/** 暗色判定：auto 跟随系统偏好，其余手动。非法输入按 light 处理。 */
export function resolveDark(mode: string, systemPrefersDark: boolean): boolean {
  if (mode === 'dark') return true
  if (mode === 'auto') return systemPrefersDark
  return false
}

/** 由主题色生成 hover/active 等派生色（与亮色系混合，保持可读性）。 */
export function deriveColors(hex: string): { light3: string; dark2: string } {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return { light3: hex, dark2: hex }
  const num = parseInt(m[1], 16)
  const mix = (to: number, ratio: number) => {
    const ch = (shift: number) => (num >> shift) & 0xff
    const blended = [0, 1, 2].map((i) =>
      Math.round(ch(i * 8) * (1 - ratio) + ((to >> (i * 8)) & 0xff) * ratio),
    )
    return `#${blended.map((v) => v.toString(16).padStart(2, '0')).join('')}`
  }
  return { light3: mix(0xffffff, 0.3), dark2: mix(0x000000, 0.2) }
}

/** 壁纸层 CSS：返回 background 与 filter/遮罩变量；none 返回空串。 */
export function wallpaperStyle(s: AppearanceSettings): Record<string, string> {
  if (s.wallpaperType === 'none' || !s.wallpaperValue) return {}
  const background =
    s.wallpaperType === 'image'
      ? `url("${s.wallpaperValue}") center/cover no-repeat`
      : s.wallpaperValue
  return {
    background,
    filter: s.wallpaperBlur > 0 ? `blur(${s.wallpaperBlur}px)` : 'none',
    opacity: String(1 - s.wallpaperMask / 100),
  }
}

/** 把外观设置应用到 document（html data-theme / CSS 变量 / 壁纸层）。 */
export function applyTheme(s: AppearanceSettings, systemPrefersDark: boolean): void {
  const dark = resolveDark(s.darkMode, systemPrefersDark)
  const el = document.documentElement
  el.dataset.theme = dark ? 'dark' : 'light'
  el.classList.toggle('dark', dark) // Element Plus 暗色变量约定
  el.style.setProperty('--p-primary', s.themeColor)
  const { light3, dark2 } = deriveColors(s.themeColor)
  el.style.setProperty('--p-primary-light3', light3)
  el.style.setProperty('--p-primary-dark2', dark2)
  el.style.setProperty('--el-color-primary', s.themeColor)
  el.style.setProperty('--el-color-primary-light-3', light3)
  el.style.setProperty('--el-color-primary-dark-2', dark2)
}
