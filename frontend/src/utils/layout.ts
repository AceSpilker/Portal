/**
 * 首页布局序列化/反序列化（M02-2/3/4；dev-plan P4.2/4.3）。
 *
 * layout JSON 契约（与后端 dashboard_layouts.layout 一致）：
 *   {
 *     order: string[]        全局扁平磁贴顺序（appId 字符串）
 *     sizes: {[appId]: 1|2}  卡片宽度（P4.3）
 *     collapsed: {[key]: bool} 区块折叠状态（fav/none/分组id）
 *     sections: string[]     区块顺序（'fav' 收藏区、'none' 未分组、其余为分组 id）
 *   }
 */
import type { Category, PortalApp } from '../api/portal'

export interface DashboardLayoutData {
  order: string[]
  sizes: Record<string, 1 | 2>
  collapsed: Record<string, boolean>
  sections: string[]
}

export const DEFAULT_LAYOUT: DashboardLayoutData = {
  order: [],
  sizes: {},
  collapsed: {},
  sections: [],
}

/** 把服务端返回解析为布局对象（兼容缺字段/类型漂移；JSON 键均为字符串）。 */
export function parseLayout(raw: unknown): DashboardLayoutData {
  const base: DashboardLayoutData = {
    order: [],
    sizes: {},
    collapsed: {},
    sections: [],
  }
  if (!raw || typeof raw !== 'object') return base
  const r = raw as Record<string, unknown>
  if (Array.isArray(r.order)) base.order = r.order.map((x) => String(x))
  if (Array.isArray(r.sections)) base.sections = r.sections.map((x) => String(x))
  if (r.sizes && typeof r.sizes === 'object') {
    base.sizes = Object.fromEntries(
      Object.entries(r.sizes as Record<string, unknown>).map(([k, v]) => [
        k,
        v === 2 || v === '2' ? 2 : 1,
      ]),
    )
  }
  if (r.collapsed && typeof r.collapsed === 'object') {
    base.collapsed = Object.fromEntries(
      Object.entries(r.collapsed as Record<string, unknown>).map(([k, v]) => [k, Boolean(v)]),
    )
  }
  return base
}

/** 与最新应用集合对齐：剔除已删 id，新应用按 sort,id 追加到末尾。 */
export function syncOrder(order: string[], apps: PortalApp[]): string[] {
  const ids = new Set(apps.map((a) => String(a.id)))
  const kept = order.filter((id) => ids.has(id))
  const known = new Set(kept)
  const appended = [...apps]
    .filter((a) => !known.has(String(a.id)))
    .sort((a, b) => a.sort - b.sort || a.id - b.id)
    .map((a) => String(a.id))
  return [...kept, ...appended]
}

/**
 * 区块内拖拽后的全局顺序：把 subset 的新相对顺序套回 order 中这些成员
 * 原本占据的位置（升序回填），未涉及的成员位置不变。用于「位置即改即存」。
 */
export function reorderSubset(order: string[], subset: string[]): string[] {
  const positions: number[] = []
  const set = new Set(subset)
  order.forEach((id, i) => {
    if (set.has(id)) positions.push(i)
  })
  const result = [...order]
  subset.forEach((id, k) => {
    if (positions[k] !== undefined) result[positions[k]] = id
  })
  // subset 中可能含 order 尚未收录的新 id：追加到末尾
  const inResult = new Set(result)
  for (const id of subset) {
    if (!inResult.has(id)) result.push(id)
  }
  return result
}

/** 按全局顺序对应用排序；不在 order 中的按 sort,id 追加（新应用兜底）。 */
export function orderedApps(apps: PortalApp[], order: string[]): PortalApp[] {
  const pos = new Map(order.map((id, i) => [id, i]))
  return [...apps].sort((a, b) => {
    const pa = pos.get(String(a.id))
    const pb = pos.get(String(b.id))
    if (pa !== undefined && pb !== undefined) return pa - pb
    if (pa !== undefined) return -1
    if (pb !== undefined) return 1
    return a.sort - b.sort || a.id - b.id
  })
}

export interface DashboardSection {
  key: string // 'fav' 收藏区 / 'none' 未分组 / 分组 id
  title: string
  collapsed: boolean
  apps: PortalApp[]
}

/** 生成区块结构：收藏区置顶（M02-9），分组区块按 sections 顺序，缺失分组按 id 序补尾。 */
export function buildSections(
  apps: PortalApp[],
  categories: Category[],
  layout: DashboardLayoutData,
): DashboardSection[] {
  const ordered = orderedApps(apps, layout.order)
  const sections: DashboardSection[] = []
  const favorites = ordered.filter((a) => a.favorite)
  if (favorites.length) {
    sections.push({ key: 'fav', title: '', collapsed: Boolean(layout.collapsed['fav']), apps: favorites })
  }

  const byId = new Map(categories.map((c) => [String(c.id), c]))
  const grouped = new Map<string, PortalApp[]>()
  const ungrouped: PortalApp[] = []
  for (const a of ordered) {
    if (a.favorite) continue
    if (a.category_id == null) ungrouped.push(a)
    else {
      const key = String(a.category_id)
      if (!grouped.has(key)) grouped.set(key, [])
      grouped.get(key)!.push(a)
    }
  }
  const presentCatKeys = [
    ...grouped.keys(),
    ...(ungrouped.length ? ['none'] : []),
  ]
  const keys = [
    ...layout.sections.filter((k) => k === 'none' || byId.has(k) || k === 'fav'),
    ...presentCatKeys.filter((k) => !layout.sections.includes(k)),
  ]
  const collapsedFor = (key: string) => {
    if (layout.collapsed[key] !== undefined) return layout.collapsed[key]
    if (key !== 'none' && byId.has(key)) return byId.get(key)!.collapsed // 分组默认折叠态
    return false
  }
  for (const key of keys) {
    if (key === 'none') {
      if (ungrouped.length)
        sections.push({ key, title: '', collapsed: collapsedFor(key), apps: ungrouped })
      continue
    }
    const inCat = grouped.get(key)
    if (!inCat?.length) continue
    sections.push({
      key,
      title: byId.get(key)?.name ?? '',
      collapsed: collapsedFor(key),
      apps: inCat,
    })
  }
  return sections
}
