/** P4 单测关卡：主题状态切换逻辑（M02-18/19/20）。 */
import { describe, expect, it } from 'vitest'
import { deriveColors, resolveDark, wallpaperStyle } from '../utils/theme'

describe('resolveDark', () => {
  it('auto 跟随系统偏好；light/dark 手动；非法输入按亮色', () => {
    expect(resolveDark('auto', true)).toBe(true)
    expect(resolveDark('auto', false)).toBe(false)
    expect(resolveDark('light', true)).toBe(false)
    expect(resolveDark('dark', false)).toBe(true)
    expect(resolveDark('whatever', true)).toBe(false)
  })
})

describe('deriveColors', () => {
  it('派生 EP 全套色阶（light-1..9 + dark-2）；非法输入原样返回', () => {
    const ladder = deriveColors('#4f6ef7')
    // 与 Element Plus 官方 mix 规则一致（亮色向白、dark-2 向黑）
    expect(ladder.light3).toBe('#849af9')
    expect(ladder.light9).toBe('#edf1fe')
    expect(ladder.dark2).toBe('#3f58c6')
    expect(ladder.light1).toMatch(/^#[0-9a-f]{6}$/)
    expect(deriveColors('not-a-color').light3).toBe('not-a-color')
    expect(deriveColors('not-a-color').dark2).toBe('not-a-color')
  })
  it('暗色模式色阶向 EP 暗底 #141414 混合、dark-2 向白混合', () => {
    const ladder = deriveColors('#4f6ef7', true)
    expect(ladder.light3).toBe('#3d53b3')
    expect(ladder.light9).toBe('#1a1d2b')
    expect(ladder.dark2).toBe('#728bf9')
  })
})

describe('wallpaperStyle', () => {
  it('none / 空值返回空样式；image 与渐变/纯色生成对应背景', () => {
    expect(wallpaperStyle({ wallpaperType: 'none', wallpaperValue: '', wallpaperBlur: 0, wallpaperMask: 35 } as never)).toEqual({})
    const img = wallpaperStyle({
      wallpaperType: 'image',
      wallpaperValue: 'https://nas/wall.jpg',
      wallpaperBlur: 6,
      wallpaperMask: 50,
    } as never)
    expect(img.background).toContain('url("https://nas/wall.jpg")')
    expect(img.filter).toBe('blur(6px)')
    expect(img.opacity).toBe('0.5')
    const grad = wallpaperStyle({
      wallpaperType: 'gradient',
      wallpaperValue: 'linear-gradient(135deg, #111, #222)',
      wallpaperBlur: 0,
      wallpaperMask: 0,
    } as never)
    expect(grad.background).toContain('linear-gradient')
    expect(grad.opacity).toBe('1')
  })
})
