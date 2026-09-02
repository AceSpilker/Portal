import { describe, expect, it } from 'vitest'
import { ELEMENT_ICONS, ELEMENT_ICON_MAP, filterElementIcons } from '../utils/elementIcons'

describe('elementIcons 图标库工具', () => {
  it('全量图标名称唯一且包含常用图标', () => {
    const names = ELEMENT_ICONS.map((i) => i.name)
    expect(new Set(names).size).toBe(names.length)
    expect(names.length).toBeGreaterThan(200)
    for (const expected of ['Monitor', 'Grid', 'Setting', 'Cloudy', 'Cpu']) {
      expect(names).toContain(expected)
    }
  })

  it('名称映射表与列表一致', () => {
    expect(ELEMENT_ICON_MAP['Monitor']).toBeDefined()
    expect(Object.keys(ELEMENT_ICON_MAP).length).toBe(ELEMENT_ICONS.length)
  })

  it('按名称模糊过滤（不区分大小写）', () => {
    expect(filterElementIcons('monitor').every((i) => i.name.toLowerCase().includes('monitor'))).toBe(true)
    expect(filterElementIcons('monitor')).toContainEqual(
      expect.objectContaining({ name: 'Monitor' }),
    )
    // 空关键字返回全量
    expect(filterElementIcons('  ')).toHaveLength(ELEMENT_ICONS.length)
    // 无匹配返回空
    expect(filterElementIcons('zzzz不存在')).toHaveLength(0)
  })
})
