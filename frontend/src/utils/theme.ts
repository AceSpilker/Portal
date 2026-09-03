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

export interface PrimaryLadder {
  light1: string
  light2: string
  light3: string
  light4: string
  light5: string
  light6: string
  light7: string
  light8: string
  light9: string
  dark2: string
}

/**
 * 由主题色派生 Element Plus 全套主色色阶（规则与 EP 官方一致）：
 * 亮色下 light-N 向白混合 N*10%、dark-2 向黑混合 20%；
 * 暗色下 light-N 向 #141414（EP 暗底）混合 N*10%、dark-2 向白混合 20%。
 */
export function deriveColors(hex: string, dark = false): PrimaryLadder {
  const ladderBase = dark ? 0x141414 : 0xffffff
  const darkBase = dark ? 0xffffff : 0x000000
  const mix = (num: number, to: number, ratio: number) => {
    // 通道按 R,G,B 取（num 高位在左），勿按字节序取成 B、G、R
    const ch = (shift: number) => (num >> shift) & 0xff
    const blended = [16, 8, 0].map((shift) =>
      Math.round(ch(shift) * (1 - ratio) + ((to >> shift) & 0xff) * ratio),
    )
    return `#${blended.map((v) => v.toString(16).padStart(2, '0')).join('')}`
  }
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  const keys = ['light1', 'light2', 'light3', 'light4', 'light5', 'light6', 'light7', 'light8', 'light9', 'dark2'] as const
  if (!m) {
    const same = {} as PrimaryLadder
    for (const k of keys) same[k] = hex.trim()
    return same
  }
  const num = parseInt(m[1], 16)
  const ladder = {} as PrimaryLadder
  for (let i = 1; i <= 9; i++) {
    ladder[`light${i}` as keyof PrimaryLadder] = mix(num, ladderBase, i / 10)
  }
  ladder.dark2 = mix(num, darkBase, 0.2)
  return ladder
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
  // EP 组件（按钮 hover/选中/plain、表格选中行、菜单、分页等）消费整条派生色阶，
  // 内联样式覆盖亮/暗两套样式表，因此必须按当前模式生成全套，缺一条就回退默认蓝
  const ladder = deriveColors(s.themeColor, dark)
  el.style.setProperty('--el-color-primary', s.themeColor)
  for (let i = 1; i <= 9; i++) {
    el.style.setProperty(`--el-color-primary-light-${i}`, ladder[`light${i}` as keyof PrimaryLadder])
  }
  el.style.setProperty('--el-color-primary-dark-2', ladder.dark2)
}
