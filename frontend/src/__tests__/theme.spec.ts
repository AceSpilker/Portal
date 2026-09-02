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
  it('从主题色派生亮/暗变体；非法输入原样返回', () => {
    const { light3, dark2 } = deriveColors('#4f6ef7')
    expect(light3).toMatch(/^#[0-9a-f]{6}$/)
    expect(dark2).toMatch(/^#[0-9a-f]{6}$/)
    expect(light3).not.toBe(dark2)
    expect(deriveColors('not-a-color')).toEqual({ light3: 'not-a-color', dark2: 'not-a-color' })
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
