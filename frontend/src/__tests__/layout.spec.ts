/** P4 单测关卡：布局序列化/反序列化与区块构建（M02-2/3/4/5）。 */
import { describe, expect, it } from 'vitest'
import {
  buildSections,
  orderedApps,
  parseLayout,
  reorderSubset,
  syncOrder,
  type DashboardLayoutData,
} from '../utils/layout'
import type { Category, PortalApp } from '../api/portal'

const app = (id: number, over: Partial<PortalApp> = {}): PortalApp => ({
  description: '',
  icon: null,
  icon_type: 'element',
  category_id: null,
  sort: 0,
  enabled: true,
  health_type: '',
  health_target: null,
  health_interval: 60,
  open_mode: 'newtab',
  visibility: 'all',
  favorite: false,
  tags: [],
  remark: '',
  doc_url: null,
  urls: [],
  ...over,
  name: over.name ?? `App${id}`,
  id,
})

const cat = (id: number, name: string, collapsed = false): Category => ({
  id,
  name,
  icon: null,
  icon_type: null,
  sort: 0,
  collapsed,
  app_count: 0,
})

const apps = [
  app(1, { name: 'A', sort: 1 }),
  app(2, { name: 'B', sort: 2, category_id: 10 }),
  app(3, { name: 'C', sort: 3, category_id: 10, favorite: true }),
  app(4, { name: 'D', sort: 4 }),
]

describe('parseLayout', () => {
  it('非法输入回退默认布局；字段类型漂移被纠正', () => {
    expect(parseLayout(null)).toEqual({ order: [], sizes: {}, collapsed: {}, sections: [] })
    const parsed = parseLayout({ order: [3, 1], sizes: { 3: '2', 4: 1 }, collapsed: { fav: 1 }, sections: ['10'] })
    expect(parsed.order).toEqual(['3', '1'])
    expect(parsed.sizes).toEqual({ 3: 2, 4: 1 })
    expect(parsed.collapsed).toEqual({ fav: true })
    expect(parsed.sections).toEqual(['10'])
  })
})

describe('syncOrder / reorderSubset', () => {
  it('syncOrder 剔除已删并按 sort 追加新应用', () => {
    expect(syncOrder(['9', '2', '1'], apps)).toEqual(['2', '1', '3', '4'])
  })

  it('reorderSubset 把新相对顺序回填到原位置（位置即改即存）', () => {
    expect(reorderSubset(['1', '2', '3', '4'], ['3', '1', '2'])).toEqual(['3', '1', '2', '4'])
    expect(reorderSubset(['1', '2'], ['2', '1'])).toEqual(['2', '1'])
    // 含新成员时追加到末尾
    expect(reorderSubset(['1'], ['1', '5'])).toEqual(['1', '5'])
  })
})

describe('buildSections', () => {
  const cats = [cat(10, '媒体', true), cat(11, '开发')]
  const baseLayout: DashboardLayoutData = {
    order: ['3', '1', '2', '4'],
    sizes: {},
    collapsed: {},
    sections: [],
  }

  it('收藏区置顶；分组按名称渲染；分组默认折叠态生效', () => {
    const sections = buildSections(apps, cats, baseLayout)
    expect(sections[0].key).toBe('fav')
    expect(sections[0].apps.map((a) => a.id)).toEqual([3])
    const media = sections.find((s) => s.title === '媒体')
    expect(media?.apps.map((a) => a.id)).toEqual([2])
    expect(media?.collapsed).toBe(true) // 分组默认折叠（布局未覆写时）
  })

  it('布局 sections 顺序决定区块顺序；未分组区块按 none 键渲染', () => {
    const layout: DashboardLayoutData = { ...baseLayout, sections: ['none', '10', 'fav'] }
    const sections = buildSections(apps, cats, layout)
    expect(sections.map((s) => s.key)).toEqual(['fav', 'none', '10']) // fav 恒置顶
    expect(sections.find((s) => s.key === 'none')?.apps.map((a) => a.id)).toEqual([1, 4])
  })
})

describe('orderedApps', () => {
  it('order 优先，未收录按 sort,id 兜底', () => {
    expect(orderedApps(apps, ['4', '1']).map((a) => a.id)).toEqual([4, 1, 2, 3])
  })
})
